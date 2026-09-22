"""End-to-end flow harness for the deployed Testing Agent — one seed in, full pipeline out.

Speaks MCP (Streamable HTTP) to the deployed gateway with GATEWAY_BEARER_TOKEN and runs the whole
pipeline non-interactively, auto-approving the client-owned gates:

  gather_knowledge -> refine -> approve -> [evaluate_pack] -> define_plan -> approve_plan ->
  implement_plan(loop while '[state: in_progress]') -> get_scenarios -> [evaluate_plan] -> benchmark_run

This exercises the REAL deployment (live Vertex / JEV / Atlassian) — the post-deploy smoke test. It
is NOT the offline CI gate (that is tests/eval/*). PASS = every stage returned without an MCP error
AND get_scenarios came back non-empty; PQS/TPS are surfaced when the eval stages ran.

Auto-approve is deliberately shallow: it runs ONE refine and ONE define_plan round (no answers) then
approves — it proves the plumbing end-to-end, it does not simulate a human answering interrogation.

Run:
  PYTHONIOENCODING=utf-8 uv run python tools/e2e_flow.py LUZ-158390
  ... --explore              # also run the noisy discovery tiers (default quiet/high-precision)
  ... --no-eval              # skip evaluate_pack/evaluate_plan (faster)
  ... --url https://.../mcp  # override gateway (else GATEWAY_URL env, else the deployed default)
  ... --json                 # machine-readable summary
  uv run python tools/e2e_flow.py --selftest   # offline: check the pure parsers, no network/token
"""

from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DEFAULT_URL = "https://mcp-gateway-v2-q5rqhzn2uq-oa.a.run.app/mcp"


# --- pure helpers (self-tested; no network) ----------------------------------------------------
def parse_ctx(gather_text: str) -> str | None:
    """gather_knowledge returns 'context_id: <ctx>\\n\\n...'. Pull the ctx."""
    m = re.search(r"context_id:\s*(\S+)", gather_text)
    return m.group(1) if m else None


def is_in_progress(text: str) -> bool:
    """A chunked reply that pauses mid-loop starts with '[state: in_progress]'."""
    return text.lstrip().startswith("[state: in_progress]")


def extract_score(text: str, *, labels: tuple[str, ...]) -> float | None:
    """Best-effort: first 0–1 (or 0–100) float following any of the score labels (PQS/TPS/Score)."""
    for lab in labels:
        m = re.search(rf"{lab}[^0-9]{{0,12}}([01]?\.\d+|\d{{1,3}}(?:\.\d+)?)", text, re.IGNORECASE)
        if m:
            v = float(m.group(1))
            return v / 100 if v > 1.5 else v
    return None


def count_scenarios(text: str) -> int:
    """Best-effort scenario count: explicit 'Scenario' headers, else top-level numbered items."""
    n = len(re.findall(r"(?im)^\s*(?:#+\s*)?scenario\b", text))
    if n:
        return n
    return len(re.findall(r"(?m)^\s*\d+[.)]\s+\S", text))


# --- MCP driver ---------------------------------------------------------------------------------
async def _run(args) -> int:
    import httpx2
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    token = os.environ.get("GATEWAY_BEARER_TOKEN", "").strip()
    url = args.url or os.environ.get("GATEWAY_URL", "").strip() or _DEFAULT_URL
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if not token:
        print("WARN: GATEWAY_BEARER_TOKEN unset — gateway will 401 if it enforces auth.", file=sys.stderr)

    summary: dict = {"seed": args.seed, "url": url, "stages": {}, "pqs": None, "tps": None,
                     "scenarios": 0, "passed": False}

    http = httpx2.AsyncClient(headers=headers, timeout=args.timeout + 30)
    async with streamable_http_client(url, http_client=http) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            async def call(name: str, arguments: dict, *, timeout: float | None = None) -> str:
                res = await s.call_tool(name, arguments, read_timeout_seconds=timeout or args.timeout)
                text = "".join(getattr(c, "text", "") for c in (res.content or []))
                if res.is_error:
                    raise RuntimeError(f"{name} returned isError: {text[:400]}")
                summary["stages"][name] = "ok"
                return text

            def log(stage: str, detail: str) -> None:
                print(f"[{stage:<11}] {detail}", flush=True)

            # 1) gather -> context_id
            g = await call("gather_knowledge",
                           {"seed": args.seed, "depth": args.depth, "explore": args.explore},
                           timeout=args.timeout)
            ctx = parse_ctx(g)
            if not ctx:
                raise RuntimeError(f"could not parse context_id from gather reply:\n{g[:400]}")
            summary["context_id"] = ctx
            log("gather", f"ctx={ctx}  reply={len(g)} chars")

            # 2) refine (one round, no answer) -> approve
            r = await call("refine", {"context_id": ctx})
            log("refine", f"state={'in_progress' if is_in_progress(r) else 'ready'} -> auto-approve")
            await call("approve", {"context_id": ctx})
            log("approve", "pack understanding confirmed")

            # 3) evaluate_pack (optional, non-blocking)
            if not args.no_eval:
                ep = await call("evaluate_pack", {"context_id": ctx})
                summary["pqs"] = extract_score(ep, labels=("PQS", "Pack Quality Score", "Score"))
                log("eval_pack", f"PQS={summary['pqs']}")

            # 4) define_plan (one round, no answer) -> approve_plan
            d = await call("define_plan", {"context_id": ctx})
            log("define", f"state={'in_progress' if is_in_progress(d) else 'ready'} -> auto-approve")
            await call("approve_plan", {"context_id": ctx})
            log("approve_plan", "plan locked to confirmed")

            # 5) implement_plan — loop while chunked in_progress
            rounds = 0
            while True:
                imp = await call("implement_plan", {"context_id": ctx}, timeout=args.timeout)
                rounds += 1
                if not is_in_progress(imp) or rounds >= args.max_implement_rounds:
                    log("implement", f"done after {rounds} round(s)"
                        + ("" if not is_in_progress(imp) else f" (hit max {args.max_implement_rounds})"))
                    break
                log("implement", f"round {rounds}: in_progress, continuing")
            summary["stages"]["implement_plan"] = "ok"

            # 6) scenarios
            sc = await call("get_scenarios", {"context_id": ctx})
            summary["scenarios"] = count_scenarios(sc)
            log("scenarios", f"~{summary['scenarios']} scenario(s), {len(sc)} chars")

            # 7) evaluate_plan (optional) + benchmark
            if not args.no_eval:
                epl = await call("evaluate_plan", {"context_id": ctx})
                summary["tps"] = extract_score(epl, labels=("TPS", "Test Plan Score", "Score"))
                log("eval_plan", f"TPS={summary['tps']}")
            bm = await call("benchmark_run", {"context_id": ctx})
            log("benchmark", f"scorecard {len(bm)} chars")

    summary["passed"] = summary["scenarios"] > 0 and all(v == "ok" for v in summary["stages"].values())
    if args.json:
        import json
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        verdict = "PASS" if summary["passed"] else "FAIL"
        print(f"\n{verdict}  seed={args.seed} ctx={summary.get('context_id')} "
              f"scenarios≈{summary['scenarios']} PQS={summary['pqs']} TPS={summary['tps']}")
    return 0 if summary["passed"] else 1


def _selftest() -> None:
    assert parse_ctx("context_id: run-ab12\n\nhi") == "run-ab12"
    assert parse_ctx("no ctx here") is None
    assert is_in_progress("[state: in_progress]\nworking") is True
    assert is_in_progress("[state: done]\nfinished") is False
    assert extract_score("Pack Quality Score: 0.82 (recall...)", labels=("PQS", "Pack Quality Score")) == 0.82
    assert extract_score("TPS = 77", labels=("TPS",)) == 0.77  # 0-100 normalised
    assert extract_score("nothing", labels=("PQS",)) is None
    assert count_scenarios("## Scenario 1\n...\n## Scenario 2\n") == 2
    assert count_scenarios("1. happy path\n2. negative\n3. edge") == 3
    print("ok")


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed-driven end-to-end smoke of the deployed Testing Agent.")
    ap.add_argument("seed", nargs="?", help="Jira seed, e.g. LUZ-158390")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--explore", action="store_true", help="also run the noisy discovery tiers")
    ap.add_argument("--no-eval", action="store_true", help="skip evaluate_pack/evaluate_plan")
    ap.add_argument("--url", help="gateway MCP url (else GATEWAY_URL env, else deployed default)")
    ap.add_argument("--timeout", type=float, default=600.0, help="per-call read timeout seconds")
    ap.add_argument("--max-implement-rounds", type=int, default=12)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="offline parser check; no network/token")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return 0
    if not args.seed:
        ap.error("seed is required (or pass --selftest)")

    try:  # load .env for GATEWAY_BEARER_TOKEN / GATEWAY_URL (mirrors the agents' load_dotenv)
        from dotenv import load_dotenv
        load_dotenv(_ROOT / ".env")
    except ImportError:
        pass

    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
