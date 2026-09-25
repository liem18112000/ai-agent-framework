#!/usr/bin/env python3
"""OpenAI-compatible shim over the local `claude` CLI (subscription).

litellm POSTs /v1/chat/completions here; we shell `claude -p` (which uses the persisted ~/.claude
login) and return the completion. Text-only, non-streaming — enough for the engine's complete() path
and ADK LlmAgent text calls. Auth lives in a mounted volume (/root/.claude); run the one-time
`claude /login` via `docker compose exec` (see docs/LOCAL-USAGE.md)."""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common.env import env_int

PORT = env_int("PORT", 8088)
_MAX_BODY = env_int("CLAUDE_PROXY_MAX_BODY", 32 * 1024 * 1024)  # reject bodies over this (unbounded-alloc guard)
# One paid `claude` CLI per slot; excess requests queue instead of forking unbounded subprocesses.
_SEM = threading.BoundedSemaphore(env_int("CLAUDE_PROXY_MAX_CONCURRENCY", 4))


def flatten(messages):
    parts = []
    for m in messages or []:
        role = {"system": "System", "assistant": "Assistant"}.get(m.get("role"), "User")
        c = m.get("content", "")
        if isinstance(c, list):
            c = "".join(p.get("text", "") for p in c)
        parts.append(f"{role}: {c}")
    return "\n\n".join(parts)


def run_claude(prompt):
    args = ["claude", "-p", prompt, "--output-format", "json"]
    if os.environ.get("CLAUDE_MODEL"):
        args += ["--model", os.environ["CLAUDE_MODEL"]]
    with _SEM:
        out = subprocess.run(args, capture_output=True, text=True, timeout=600, check=False).stdout
    try:
        j = json.loads(out)
    except json.JSONDecodeError:
        return out
    # An empty "result" is a valid (empty) completion — don't fall through to dumping the raw JSON blob.
    return j["result"] if "result" in j else j.get("response", out)


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/health", "/livez"):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if not self.path.startswith("/v1/chat/completions"):
            self.send_response(404); self.end_headers(); return
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n > _MAX_BODY:
                self._json(413, {"error": {"message": f"request body too large (> {_MAX_BODY} bytes)"}})
                return
            req = json.loads(self.rfile.read(n) or b"{}")
            text = run_claude(flatten(req.get("messages")))
            self._json(200, {
                "id": "claude-local", "object": "chat.completion", "created": 0, "model": "claude-local",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                             "finish_reason": "stop"}],
                "usage": {},
            })
        except Exception as e:  # noqa: BLE001 — surface any CLI/parse error as a 500 to the client
            self._json(500, {"error": {"message": str(e)}})

    def log_message(self, *a):  # quiet the default per-request stderr spam
        pass


if __name__ == "__main__":
    print(f"claude-proxy on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
