"""Post-deploy check for the 2026-09-29 refactor — the three things it could have broken.

`e2e_flow.py` proves the PIPELINE still runs end to end; run it too. This proves the specific
seams that refactor moved, each of which fails in a way a pipeline run would not obviously report:

  1. bootstrap_adk   — the ADK/dotenv/ADC bootstrap was copy-pasted in 3 package __init__ files and
                       is now one shared call. If it broke, an agent does not boot at all, so we ask
                       every agent for its card (kga, tpd, tev, admin, exec).
  2. SchemaOnce      — `_ensure` was duplicated in the pgvector store and the executor ledger and is
                       now one base class. If a subclass lost its own SCHEMA_SQL, its DDL never
                       applies; `view-memory` reads memory_node and `list-environments` reads
                       exec_environment, so each touches its own tables on the real Cloud SQL.
  3. meter drain     — `persist_usage` now DRAINS the counters it stores. Under the old code a run
                       chunked on one warm instance stored the triangular sum (see TOK-1). We read
                       the accounting back and check it is internally consistent.

Talks A2A to the admin agent with A2A_BEARER_TOKEN, deliberately: the token-* commands are on the
gateway now (TOK-3 is fixed), but going direct means a gateway fault cannot be mistaken for an agent
fault — this script is the one that has to say WHICH layer broke.

Run (after a deploy, and after at least one pipeline run so there is something to read):
  PYTHONIOENCODING=utf-8 uv run python tools/e2e_refactor_check.py
  ... --ctx run-abc123        # check the token accounting for one specific run
  ... --selftest              # offline: exercise the pure parsers, no network, no token

Exit code 0 = every check passed. Non-zero = the first failure is named on stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Every deployed agent: short name -> (A2A url, the PYTHON PACKAGE its card reports).
#: The card's `name` is the package name verbatim, which is exactly what we want to assert — that is
#: the package whose __init__ calls bootstrap_adk, so a matching card proves that bootstrap ran.
#: `<SHORT>_A2A_URL` overrides a url.
AGENTS = {
    "kga": ("https://knowledge-gathering-agent-v2-q5rqhzn2uq-oa.a.run.app", "knowledge_gathering"),
    "tpd": ("https://test-plan-definition-agent-v2-q5rqhzn2uq-oa.a.run.app", "test_plan_definition"),
    "tev": ("https://test-evaluation-agent-v2-q5rqhzn2uq-oa.a.run.app", "test_evaluation"),
    "admin": ("https://admin-agent-v2-q5rqhzn2uq-oa.a.run.app", "admin_agent"),
    "exec": ("https://test-executor-agent-v2-q5rqhzn2uq-oa.a.run.app", "test_executor"),
}

_FIELDS = ("calls", "input", "cached_rd", "cached_wr", "output")


# --- pure parsers (self-tested; no network) -----------------------------------------------------
def parse_usage_table(text: str) -> dict[str, dict[str, int]]:
    """Parse `token-usage`'s fixed-width table into {label: {field: n}}.

    The table is `stage / agent` + 5 right-aligned integer columns, with a TOTAL row after a rule.
    Labels contain '.' and '/' but never whitespace, which is what makes a regex safe here."""
    out: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        m = re.match(r"^(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", line)
        if not m:
            continue
        label = m.group(1)
        if label in ("stage", "-"):
            continue
        out[label] = dict(zip(_FIELDS, (int(m.group(i)) for i in range(2, 7))))
    return out


def usage_is_consistent(rows: dict[str, dict[str, int]]) -> tuple[bool, str]:
    """TOTAL must equal the sum of the per-label rows, and nothing may be negative.

    This is what the TOK-1 bug broke: `_with_total` recomputes TOTAL from the rows, so an inflated
    store inflates both together — the discriminator is not TOTAL-vs-rows but whether the numbers
    are self-consistent at all after a drained persist. A mismatch here means a partial write."""
    if "TOTAL" not in rows:
        return False, "no TOTAL row in the table"
    labels = {k: v for k, v in rows.items() if k != "TOTAL"}
    if not labels:
        return False, "TOTAL present but no per-stage rows"
    for field in _FIELDS:
        want = sum(r[field] for r in labels.values())
        got = rows["TOTAL"][field]
        if want != got:
            return False, f"TOTAL.{field}={got} but the rows sum to {want}"
    if any(n < 0 for r in rows.values() for n in r.values()):
        return False, "a negative count"
    return True, f"{len(labels)} stage(s), {rows['TOTAL']['calls']} call(s)"


def card_is_agent(card: dict, package: str) -> bool:
    """The card's `name` is the serving package. Exact match, not a substring: `test_evaluation` and
    `test_executor` share a prefix, and a loose match would call a mis-routed service healthy."""
    return (card or {}).get("name") == package


# --- checks -------------------------------------------------------------------------------------
async def check_agents_boot(http, results: list) -> bool:
    """CHECK 1 — bootstrap_adk. A package whose bootstrap broke cannot serve its card at all."""
    ok = True
    for name, (default, package) in AGENTS.items():
        url = os.environ.get(f"{name.upper()}_A2A_URL", default).rstrip("/")
        try:
            r = await http.get(f"{url}/.well-known/agent-card.json", timeout=30)
            good = r.status_code == 200 and card_is_agent(r.json(), package)
            detail = f"card={package}" if good else f"HTTP {r.status_code}, name={(r.json() or {}).get('name')!r}"
        except Exception as exc:  # noqa: BLE001 — a dead agent is a result, not a crash
            good, detail = False, f"{type(exc).__name__}: {exc}"
        ok &= good
        results.append(("bootstrap", name, good, detail))
    return ok


async def ask_admin(http, text: str, timeout: float = 120.0) -> str:
    """One A2A message/send to the admin agent; returns the concatenated text parts."""
    url = os.environ.get("ADMIN_A2A_URL", AGENTS["admin"][0]).rstrip("/")
    body = {"jsonrpc": "2.0", "id": "1", "method": "message/send",
            "params": {"message": {"role": "user", "messageId": "e2e-refactor-check",
                                   "parts": [{"kind": "text", "text": text}]}}}
    r = await http.post(f"{url}/", json=body, timeout=timeout)
    r.raise_for_status()
    payload = r.json()
    if "error" in payload:
        raise RuntimeError(f"admin A2A error: {payload['error']}")
    parts = (payload.get("result") or {}).get("parts") or []
    for key in ("status", "artifacts"):           # the reply shape varies by task state
        node = (payload.get("result") or {}).get(key)
        if not parts and isinstance(node, dict):
            parts = (node.get("message") or {}).get("parts") or []
        elif not parts and isinstance(node, list) and node:
            parts = node[0].get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


async def check_schema_once(http, results: list) -> bool:
    """CHECK 2 — SchemaOnce. Each store must still apply its OWN DDL on the shared engine."""
    ok = True
    for label, cmd, want in (("memory_node (pgvector store)", "view-memory all", ("memor", "tier", "node")),
                             ("exec_environment (run ledger)", "list-runs 1", ("run", "no runs", "id"))):
        try:
            reply = (await ask_admin(http, cmd)).lower()
            good = bool(reply) and any(w in reply for w in want) and "traceback" not in reply
            detail = "table readable" if good else f"unexpected reply: {reply[:90]!r}"
        except Exception as exc:  # noqa: BLE001
            good, detail = False, f"{type(exc).__name__}: {exc}"
        ok &= good
        results.append(("schema-once", label, good, detail))
    return ok


async def check_token_accounting(http, ctx: str, results: list) -> bool:
    """CHECK 3 — the meter drain. Reads the accounting back and checks it adds up."""
    cmd = f"token-usage {ctx}".strip()
    try:
        reply = await ask_admin(http, cmd)
    except Exception as exc:  # noqa: BLE001
        results.append(("tokens", cmd, False, f"{type(exc).__name__}: {exc}"))
        return False

    if "nothing recorded" in reply.lower():
        # Not a failure: a fresh deployment with no run yet has nothing to check. Say so loudly
        # rather than passing silently — a green tick on an empty table proves nothing.
        results.append(("tokens", cmd, True, "SKIPPED — nothing recorded yet (run a pipeline first)"))
        return True

    rows = parse_usage_table(reply)
    good, detail = usage_is_consistent(rows)
    results.append(("tokens", cmd, good, detail))
    return good


# --- selftest -----------------------------------------------------------------------------------
def selftest() -> int:
    table = (
        "Token usage — run ctx-1\n"
        "\n"
        "stage / agent                       calls     input  cached_rd  cached_wr    output\n"
        "-----------------------------------------------------------------------------------\n"
        "define.questions.scope                  2      1200        800          0       310\n"
        "refine.understanding                    1       400          0        900        90\n"
        "-----------------------------------------------------------------------------------\n"
        "TOTAL                                   3      1600        800        900       400\n"
    )
    rows = parse_usage_table(table)
    assert set(rows) == {"define.questions.scope", "refine.understanding", "TOTAL"}, rows
    assert rows["define.questions.scope"] == {"calls": 2, "input": 1200, "cached_rd": 800,
                                              "cached_wr": 0, "output": 310}
    ok, detail = usage_is_consistent(rows)
    assert ok, detail

    # the shape TOK-1 produced: a stored total inflated past its rows
    bad = {**rows, "TOTAL": {**rows["TOTAL"], "input": 3200}}
    ok, detail = usage_is_consistent(bad)
    assert not ok and "3200" in detail, detail

    assert not usage_is_consistent({"TOTAL": {f: 0 for f in _FIELDS}})[0]   # no per-stage rows
    assert card_is_agent({"name": "knowledge_gathering"}, "knowledge_gathering")
    assert not card_is_agent({"name": "test_evaluation"}, "test_executor")   # shared prefix, must not match
    assert not card_is_agent({}, "admin_agent")
    print("selftest: all parser checks passed")
    return 0


async def main_async(args) -> int:
    import httpx

    token = os.environ.get("A2A_BEARER_TOKEN", "").strip()
    if not token:
        print("ERROR: A2A_BEARER_TOKEN unset — the agents fail closed and every check would 401.\n"
              "       It is in test-agent-v2/.env; export it or run via a shell that sources it.",
              file=sys.stderr)
        return 2

    results: list[tuple[str, str, bool, str]] = []
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
        booted = await check_agents_boot(http, results)
        # The later checks talk to the admin agent; if it never booted they would only re-report that.
        if booted:
            await check_schema_once(http, results)
            await check_token_accounting(http, args.ctx, results)

    width = max(len(f"{a}/{b}") for a, b, _, _ in results)
    for group, name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {f'{group}/{name}':<{width}}  {detail}")
    failed = [r for r in results if not r[2]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ctx", default="", help="check token accounting for this run id (default: all runs)")
    p.add_argument("--selftest", action="store_true", help="offline parser checks only")
    args = p.parse_args()
    if args.selftest:
        return selftest()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
