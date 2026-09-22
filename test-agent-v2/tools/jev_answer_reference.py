"""JEV reference column for interrogation digests — score each recommended answer against the state.

When a refine/define round (or any question we put to the user) comes back with a *recommended
answer*, this attaches JEV's own verdict as a reference: given "the state we have now" (the gathered
pack / current context), how well does that answer hold up? Default primitive is **Noul** — one
calibrated ``P(true)`` per row (``a Noul is okay``); ``--score`` switches to an ordinal **Score**
(0–1 support + confidence). It is a *reference display*, not a gate — nothing is auto-accepted or
dropped (so J4's accept-side negative doesn't apply); the number rides alongside our recommendation.

Uses the real ``JevProvider`` directly (independent of ``TPD_DECISION_BACKEND`` — this is always JEV),
loading ``test-agent-v2/.env`` for ``TYPESAFE_API_KEY``. Unconfigured → clear message, exit 2.

Run:
  PYTHONIOENCODING=utf-8 uv run python tools/jev_answer_reference.py \
      --state-file state.txt --rows-file rows.json          # Noul P(true)
  ... --score                                               # ordinal Score instead
  echo '[{"question":"...","answer":"..."}]' | uv run python tools/jev_answer_reference.py --state "..."
  uv run python tools/jev_answer_reference.py --selftest     # offline, no network/key

rows JSON = list of {"question": str, "answer": str, "id": str?}.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]  # test-agent-v2/
sys.path.insert(0, str(_ROOT / "src"))

from common.adk.providers.decision import Verdict  # noqa: E402
from common.adk.providers.jev import JevProvider  # noqa: E402

_SCORE_LEVELS = ["contradicted", "unsupported", "supported", "strongly-supported"]


def _noul_statement(question: str, answer: str) -> str:
    return f"Given the current state, «{answer}» is the correct answer to: {question}"


def _score_instructions(question: str, answer: str) -> str:
    return f"How well the current state supports «{answer}» as the answer to: {question}"


def _ref(v: Verdict, *, score: bool) -> tuple[float, float | None]:
    """(reference number, confidence-or-None). Noul → P(true) from probs['true']; Score → its 0–1 value."""
    if score:
        return float(v.value), v.confidence
    p = (v.probs or {}).get("true")
    return (float(p) if p is not None else float(bool(v.value))), None


def evaluate(rows: list[dict], state: str, *, score: bool, provider=None) -> list[dict]:
    provider = provider or JevProvider()
    out = []
    for i, row in enumerate(rows, 1):
        q, a = row.get("question", ""), row.get("answer", "")
        if score:
            v = provider.score(state, _score_instructions(q, a), _SCORE_LEVELS)
        else:
            v = provider.noul(state, _noul_statement(q, a))
        num, conf = _ref(v, score=score)
        out.append({"id": row.get("id", f"#{i}"), "question": q, "answer": a,
                    "jev": round(num, 3), "confidence": (round(conf, 3) if conf is not None else None)})
    return out


def _md_table(results: list[dict], *, score: bool) -> str:
    head = "JEV Score (0–1)" if score else "JEV P(true)"
    lines = [f"| # | Question | Recommended answer | {head} |",
             "|---|---|---|---|"]
    for r in results:
        cell = f"{r['jev']:.2f}" + (f" (conf {r['confidence']:.2f})" if r["confidence"] is not None else "")
        q = r["question"].replace("|", "\\|")
        a = r["answer"].replace("|", "\\|")
        lines.append(f"| {r['id']} | {q} | {a} | **{cell}** |")
    return "\n".join(lines)


def _selftest() -> None:
    assert _ref(Verdict(value=True, probs={"true": 0.83}, confidence=0.66), score=False) == (0.83, None)
    assert _ref(Verdict(value=False, probs=None, confidence=0.9), score=False) == (0.0, None)  # bool fallback
    assert _ref(Verdict(value=0.7, probs=None, confidence=0.9), score=True) == (0.7, 0.9)
    rows = [{"question": "Q1", "answer": "A1"}]
    fake = type("F", (), {"noul": lambda self, s, st: Verdict(True, {"true": 0.9}, 0.8)})()
    assert evaluate(rows, "state", score=False, provider=fake)[0]["jev"] == 0.9
    print("ok")


def main() -> int:
    ap = argparse.ArgumentParser(description="Attach a JEV reference verdict to each recommended answer.")
    ap.add_argument("--state", help="the current state as a string")
    ap.add_argument("--state-file", type=pathlib.Path, help="file holding the current state")
    ap.add_argument("--rows-file", type=pathlib.Path, help="JSON list of {question, answer, id?}; else stdin")
    ap.add_argument("--score", action="store_true", help="use JEV Score (ordinal) instead of Noul (P true)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a markdown table")
    ap.add_argument("--selftest", action="store_true", help="offline mapping check; no network/key")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return 0

    try:  # load .env so TYPESAFE_API_KEY is present (mirrors the agents' load_dotenv at import)
        from dotenv import load_dotenv
        load_dotenv(_ROOT / ".env")
    except ImportError:
        pass

    provider = JevProvider()
    if not provider.is_configured():
        print("JEV not configured: set TYPESAFE_API_KEY (in .env or the env) and install the `jev` extra.",
              file=sys.stderr)
        return 2

    state = args.state or (args.state_file.read_text(encoding="utf-8") if args.state_file else "")
    if not state.strip():
        print("no state given: pass --state or --state-file (JEV needs 'the state we have now').",
              file=sys.stderr)
        return 2
    raw = args.rows_file.read_text(encoding="utf-8") if args.rows_file else sys.stdin.read()
    rows = json.loads(raw)

    results = evaluate(rows, state, score=args.score, provider=provider)
    print(json.dumps(results, ensure_ascii=False, indent=2) if args.json
          else _md_table(results, score=args.score))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
