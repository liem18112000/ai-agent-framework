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
  ... --answers ans.json     # feed canned per-round answers (else 1 shallow round each, then approve)
  ... --url https://.../mcp  # override gateway (else GATEWAY_URL env, else the deployed default)
  ... --json                 # machine-readable summary
  uv run python tools/e2e_flow.py --selftest   # offline: check the pure parsers, no network/token

--answers JSON = {"refine": ["round-1 answer", "round-2 answer", ...], "define": [...]} — both keys
optional, each a list of free-text answers. The phase runs one start round then feeds the answers in
order (N answers => N+1 rounds), then approves. A missing/empty phase falls back to one shallow round.
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
    """First number after the ':'/'=' that follows a score label on the same line. Anchoring on the
    separator matters: the context_id can sit between label and score ('Pack Quality Score for
    run-b2665a81: 0.75') and its digits would otherwise be grabbed. Normalises a 0–100 value to 0–1."""
    for lab in labels:
        m = re.search(rf"{lab}[^\n:=]*[:=]\s*([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE)
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


def normalize_answers(data) -> dict[str, list[str]]:
    """Validate the parsed --answers object into {'refine': [...], 'define': [...]} (lists of str)."""
    if not isinstance(data, dict):
        raise ValueError("--answers must be a JSON object keyed by phase ('refine' / 'define')")
    out = {}
    for phase in ("refine", "define"):
        v = data.get(phase, [])
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ValueError(f"--answers['{phase}'] must be a list of strings")
        out[phase] = v
    return out


def load_answers(path: str | None) -> dict[str, list[str]]:
    """Read + validate the canned-answers JSON file (empty phases when no path given)."""
    if not path:
        return {"refine": [], "define": []}
    import json
    return normalize_answers(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))


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

    answers = load_answers(args.answers)  # read+validate before connecting so a bad file fails fast
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

            async def interrogate(tool: str, phase: str) -> bool:
                """Drive the interrogation to FINALIZE (that's when the plan/understanding is written —
                interrogation.py only calls finalize() when next_questions() is None). Feed the canned
                answers for `phase` first, then auto-accept the remaining rounds, until the reply is the
                finalize summary ('... complete') or the empty-pack notice ('Nothing to ...'), bounded by
                --max-interrogation-rounds. Returns True iff it finalized. NOTE: the '[state: completed]'
                prefix contains 'complete', so match the summary phrases, not a bare 'complete'."""
                reply = await call(tool, {"context_id": ctx})  # round 1: start, surfaces questions
                canned = list(answers[phase])
                rounds = 1
                while rounds < args.max_interrogation_rounds:
                    low = reply.lower()
                    if "nothing to " in low:
                        log(tool, f"EMPTY pack after {rounds} round(s) — {reply.splitlines()[-1][:80]}")
                        return False
                    if "definition complete" in low or "refinement complete" in low:
                        break
                    ans = canned.pop(0) if canned else "Accept the recommended answer for every open question."
                    reply = await call(tool, {"context_id": ctx, "answer": ans})
                    rounds += 1
                finalized = any(s in reply.lower() for s in ("definition complete", "refinement complete"))
                log(tool, f"{rounds} round(s) ({len(answers[phase])} canned); "
                    f"{'FINALIZED' if finalized else 'NOT finalized (hit cap)'}")
                return finalized

            # 1) gather -> context_id
            g = await call("gather_knowledge",
                           {"seed": args.seed, "depth": args.depth, "explore": args.explore},
                           timeout=args.timeout)
            ctx = parse_ctx(g)
            if not ctx:
                raise RuntimeError(f"could not parse context_id from gather reply:\n{g[:400]}")
            summary["context_id"] = ctx
            log("gather", f"ctx={ctx}  reply={len(g)} chars")

            # 2) refine (drive to finalize) -> approve
            await interrogate("refine", "refine")
            ap = await call("approve", {"context_id": ctx})
            log("approve", ap.splitlines()[0][:90] if ap.strip() else "ok")

            # 3) evaluate_pack (optional, non-blocking)
            if not args.no_eval:
                ep = await call("evaluate_pack", {"context_id": ctx})
                summary["pqs"] = extract_score(ep, labels=("PQS", "Pack Quality Score", "Score"))
                log("eval_pack", f"PQS={summary['pqs']}")

            # 4) define_plan (drive to finalize) -> approve_plan
            plan_ok = await interrogate("define_plan", "define")
            apl = await call("approve_plan", {"context_id": ctx})
            log("approve_plan", apl.splitlines()[0][:90])
            if not plan_ok or apl.lower().startswith("no test plan"):
                summary["stages"]["define_plan"] = "no-plan"  # forces FAIL + shows the real reason

            # 5) implement_plan — drive to generation. implement nests its OWN design interrogation
            # (case/data/step): a bare implement_plan call auto-advances one design round, so KEEP
            # calling while the reply is a design question ('answer each'/'Implement design') OR an
            # assured-loop chunk ('[state: in_progress]'), until the generation summary. (implement_plan
            # takes no answer param — the bare call is what advances the round.)
            rounds = 0
            while rounds < args.max_implement_rounds:
                imp = await call("implement_plan", {"context_id": ctx}, timeout=args.timeout)
                rounds += 1
                low = imp.lower()
                if is_in_progress(imp) or "answer each" in low or "implement design" in low:
                    continue
                break  # generation summary / done
            log("implement", f"done after {rounds} round(s)")
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
    # regression: the context_id between label and score must NOT be grabbed (was 2.66 from 'run-b2665a81')
    assert extract_score("Pack Quality Score for run-b2665a81: 0.75", labels=("Score",)) == 0.75
    assert count_scenarios("## Scenario 1\n...\n## Scenario 2\n") == 2
    assert count_scenarios("1. happy path\n2. negative\n3. edge") == 3
    assert normalize_answers({"refine": ["a", "b"]}) == {"refine": ["a", "b"], "define": []}
    assert normalize_answers({}) == {"refine": [], "define": []}
    for bad in ([1, 2], {"refine": [1]}, {"define": "x"}):
        try:
            normalize_answers(bad)
            raise AssertionError(f"expected ValueError for {bad!r}")
        except ValueError:
            pass
    print("ok")


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed-driven end-to-end smoke of the deployed Testing Agent.")
    ap.add_argument("seed", nargs="?", help="Jira seed, e.g. LUZ-158390")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--explore", action="store_true", help="also run the noisy discovery tiers")
    ap.add_argument("--no-eval", action="store_true", help="skip evaluate_pack/evaluate_plan")
    ap.add_argument("--answers", help="JSON file of canned per-round answers {refine:[...], define:[...]}")
    ap.add_argument("--url", help="gateway MCP url (else GATEWAY_URL env, else deployed default)")
    ap.add_argument("--timeout", type=float, default=600.0, help="per-call read timeout seconds")
    ap.add_argument("--max-implement-rounds", type=int, default=12)
    ap.add_argument("--max-interrogation-rounds", type=int, default=8,
                    help="cap on refine/define rounds driven to finalize (canned answers + auto-accept)")
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
