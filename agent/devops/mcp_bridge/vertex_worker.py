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

"""Standalone worker that makes the actual Vertex AI Agent Engine call.

Run as a plain script (no asyncio event loop, no threads) and spawned as a
fresh subprocess per call by server.py. This is deliberate: grpc's C-core
(initialized the first time the Agent Engine client touches the network)
deadlocks when it has to coexist in one process with the asyncio event
loop FastMCP's stdio transport already has running -- verified by
reproducing it with real Vertex AI calls (indefinite hang, frozen CPU) and
ruling it out for a plain time.sleep(), a nested asyncio.run(), and a
restricted subprocess environment run outside any event loop (all
completed normally). Isolating the Vertex AI call in its own plain
process, exactly like the working repro, sidesteps the conflict entirely.

Reads one JSON object from stdin, writes one JSON object to stdout:
  {"action": "query", "user_id": str, "session_id": str, "message": str}
  {"action": "resume", "user_id": str, "session_id": str,
   "confirmation_fc_id": str, "approve": bool}
->
  {"session_id": str, "events": [...]}   -- raw ADK event dicts
  {"error": str}                          -- on failure, with exit code 1
"""

from __future__ import annotations

import contextlib
import json
import sys

from config import CONFIRMATION_FUNCTION_NAME, LOCATION, PROJECT_ID, RESOURCE_NAME


def main() -> None:
    payload = json.loads(sys.stdin.read())
    action = payload["action"]
    user_id = payload["user_id"]
    session_id = payload.get("session_id") or ""

    with contextlib.redirect_stdout(sys.stderr):
        import vertexai
        from vertexai import agent_engines

        vertexai.init(project=PROJECT_ID, location=LOCATION)
        engine = agent_engines.get(RESOURCE_NAME)

        if action == "query":
            if not session_id:
                session = engine.create_session(user_id=user_id)
                session_id = session["id"]
            events = list(
                engine.stream_query(
                    user_id=user_id, session_id=session_id, message=payload["message"]
                )
            )
        elif action == "resume":
            resume_message = {
                "role": "user",
                "parts": [
                    {
                        "function_response": {
                            "id": payload["confirmation_fc_id"],
                            "name": CONFIRMATION_FUNCTION_NAME,
                            "response": {"confirmed": payload["approve"]},
                        }
                    }
                ],
            }
            events = list(
                engine.stream_query(
                    user_id=user_id, session_id=session_id, message=resume_message
                )
            )
        else:
            raise ValueError(f"unknown action {action!r}")

    print(json.dumps({"session_id": session_id, "events": events}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 -- reported to the parent, not swallowed
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
