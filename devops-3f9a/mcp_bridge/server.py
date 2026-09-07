# Copyright 2026 LUZ Ops
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Local MCP bridge exposing the deployed devops-3f9a Agent Engine to
Claude Code (or any other MCP client) running on this machine.

Two tools:
  - ask_devops_agent(message, session_id=None): sends a message, returns
    the agent's text response. If the agent wants to run a mutating tool
    (resize_node_pool / restart_deployment / scale_deployment), this
    surfaces the pending confirmation instead of running it, and tells
    the caller the session_id to use with confirm_devops_agent_action.
  - confirm_devops_agent_action(session_id, approve): resumes a paused
    mutating tool call by answering ADK's tool-confirmation request.

This process holds pending-confirmation state in memory only -- it is not
persisted, and is meant to be run locally as a stdio MCP server, one
instance per Claude Code session.
"""

from __future__ import annotations

from typing import Optional

from mcp.server.fastmcp import FastMCP

PROJECT_ID = "klara-nonprod"
LOCATION = "us-central1"
RESOURCE_NAME = "projects/335505349498/locations/us-central1/reasoningEngines/5955858224837033984"

CONFIRMATION_FUNCTION_NAME = "adk_request_confirmation"

mcp = FastMCP("devops-3f9a-bridge")

_agent_engine = None
_vertexai_initialized = False

# session_id -> {"confirmation_fc_id": str, "hint": str, "original_call": dict}
_pending_confirmations: dict[str, dict] = {}


def _get_agent_engine():
    global _agent_engine, _vertexai_initialized
    # `vertexai` and `vertexai.agent_engines` pull in a heavy dependency
    # tree (grpc, protobuf, google-cloud-*) that takes 10-25s to import.
    # Importing them lazily, on the first actual tool call rather than at
    # module load, lets mcp.run(transport="stdio") start listening
    # immediately -- otherwise the MCP client's handshake times out
    # waiting for the server and reports CONNECTION_CLOSED.
    import vertexai
    from vertexai import agent_engines

    if not _vertexai_initialized:
        vertexai.init(project=PROJECT_ID, location=LOCATION)
        _vertexai_initialized = True
    if _agent_engine is None:
        _agent_engine = agent_engines.get(RESOURCE_NAME)
    return _agent_engine


def _extract_confirmation_request(events: list[dict]) -> Optional[dict]:
    """Looks for an `adk_request_confirmation` function call in the events
    from this turn, and returns its id + hint + original tool call if found.
    """
    for event in events:
        parts = event.get("content", {}).get("parts", [])
        for part in parts:
            fc = part.get("function_call")
            if fc and fc.get("name") == CONFIRMATION_FUNCTION_NAME:
                args = fc.get("args", {})
                return {
                    "confirmation_fc_id": fc.get("id"),
                    "hint": args.get("hint", ""),
                    "original_call": args.get("originalFunctionCall", {}),
                }
    return None


def _extract_text(events: list[dict]) -> str:
    chunks = []
    for event in events:
        parts = event.get("content", {}).get("parts", [])
        for part in parts:
            if "text" in part and part["text"]:
                chunks.append(part["text"])
    return "\n".join(chunks)


@mcp.tool()
def ask_devops_agent(message: str, session_id: str = "") -> str:
    """Send a message to the devops-3f9a GKE ops agent (running on Vertex AI
    Agent Engine in klara-nonprod) and return its response.

    If the agent wants to run a mutating action (resize a node pool,
    restart a deployment, or scale a deployment) it will NOT run it yet --
    this returns a description of the pending action and a session_id.
    Call confirm_devops_agent_action with that session_id to approve or
    reject it before it runs.

    Args:
        message: What to ask or tell the agent.
        session_id: Session to continue, or empty to start a new one.
    """
    engine = _get_agent_engine()
    user_id = "claude-code-local"

    if not session_id:
        session = engine.create_session(user_id=user_id)
        session_id = session["id"]

    events = list(
        engine.stream_query(user_id=user_id, session_id=session_id, message=message)
    )

    pending = _extract_confirmation_request(events)
    if pending:
        _pending_confirmations[session_id] = pending
        original = pending["original_call"]
        return (
            f"[session_id={session_id}] The agent wants to run "
            f"`{original.get('name')}` with args {original.get('args')}.\n"
            f"Reason: {pending['hint'] or '(no hint given)'}\n\n"
            "This is a mutating action and has NOT run yet. Call "
            "confirm_devops_agent_action(session_id, approve=True) to run it, "
            "or approve=False to reject it."
        )

    text = _extract_text(events)
    return f"[session_id={session_id}] {text}"


@mcp.tool()
def confirm_devops_agent_action(session_id: str, approve: bool) -> str:
    """Approve or reject a pending mutating action from a prior
    ask_devops_agent call.

    Args:
        session_id: The session_id returned by the ask_devops_agent call
            that surfaced the pending confirmation.
        approve: True to let the action run, False to reject it.
    """
    pending = _pending_confirmations.pop(session_id, None)
    if pending is None:
        return (
            f"No pending confirmation found for session_id={session_id}. "
            "It may have already been resolved, or the session_id is wrong."
        )

    engine = _get_agent_engine()
    user_id = "claude-code-local"

    resume_message = {
        "role": "user",
        "parts": [
            {
                "function_response": {
                    "id": pending["confirmation_fc_id"],
                    "name": CONFIRMATION_FUNCTION_NAME,
                    "response": {"confirmed": approve},
                }
            }
        ],
    }

    events = list(
        engine.stream_query(
            user_id=user_id, session_id=session_id, message=resume_message
        )
    )
    text = _extract_text(events)
    verdict = "approved" if approve else "rejected"
    return f"[session_id={session_id}] Action {verdict}.\n{text}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
