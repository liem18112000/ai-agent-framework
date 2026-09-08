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

The actual Vertex AI Agent Engine call is delegated to vertex_worker.py,
run as a fresh subprocess per call, rather than made in this process.
Loading vertexai/grpc here and letting it touch the network while this
process's own asyncio event loop is busy running the MCP stdio transport
deadlocks indefinitely on Windows (reproduced with real calls; ruled out
for a plain sleep, a nested asyncio.run(), and a thread-offloaded call --
only the combination of grpc's C-core and this process's own event loop
hangs). A plain subprocess has no event loop of its own, so it never hits
the conflict.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

WORKER_SCRIPT = str(Path(__file__).parent / "vertex_worker.py")
CONFIRMATION_FUNCTION_NAME = "adk_request_confirmation"
USER_ID = "claude-code-local"

mcp = FastMCP("devops-3f9a-bridge")

# session_id -> {"confirmation_fc_id": str, "hint": str, "original_call": dict}
_pending_confirmations: dict[str, dict] = {}


async def _call_worker(payload: dict) -> dict:
    """Runs vertex_worker.py as a fresh subprocess with the given JSON
    payload on stdin, and returns its parsed JSON stdout.
    """
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        WORKER_SCRIPT,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(json.dumps(payload).encode())
    if proc.returncode != 0:
        raise RuntimeError(
            f"vertex_worker.py failed (exit {proc.returncode}): "
            f"{stderr.decode(errors='replace')[-2000:]}"
        )
    return json.loads(stdout.decode())


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
async def ask_devops_agent(message: str, session_id: str = "") -> str:
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
    result = await _call_worker(
        {
            "action": "query",
            "user_id": USER_ID,
            "session_id": session_id,
            "message": message,
        }
    )
    session_id = result["session_id"]
    events = result["events"]

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
async def confirm_devops_agent_action(session_id: str, approve: bool) -> str:
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

    result = await _call_worker(
        {
            "action": "resume",
            "user_id": USER_ID,
            "session_id": session_id,
            "confirmation_fc_id": pending["confirmation_fc_id"],
            "approve": approve,
        }
    )
    text = _extract_text(result["events"])
    verdict = "approved" if approve else "rejected"
    return f"[session_id={session_id}] Action {verdict}.\n{text}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
