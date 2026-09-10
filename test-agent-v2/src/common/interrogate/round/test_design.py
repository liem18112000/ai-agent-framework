"""Test-design define round (TPD, 4th round): pick the test-design method(s) that drive case
enumeration toward 100% coverage. The agent SUGGESTS the method from the pack's shape (the KGA-gathered
notes/insights + confirmed understanding); the human accepts, changes, or adds more."""

from __future__ import annotations

from common.interrogate.pack import Pack
from common.interrogate.round.base import QFactory, RoundQuestions
from common.models import Note, Question

# The canonical test-design methods offered as options (label -> one-line implication).
METHOD_OPTIONS = [
    ("Equivalence Partitioning + Boundary Value Analysis",
     "one case per input class + its edges — the base enumerator"),
    ("Decision table / cause-effect", "one rule per condition-combination — combinational logic"),
    ("State-transition testing", "cover states + valid/invalid transitions — stateful flows"),
    ("Pairwise (t-way) combinatorial", "all value pairs — bounds many-parameter explosion"),
    ("Error-path / fault injection", "one case per dependency failure mode"),
    ("Risk-based depth", "stack methods on high-risk (money/auth/data-loss/compliance) behaviours"),
]

# Signal -> method: keyword groups scanned in the pack summary. Order = recommendation order.
_SIGNALS: list[tuple[tuple[str, ...], str]] = [
    (("state", "status", "lifecycle", "stage", "transition", "workflow", "dunning"),
     "State-transition testing"),
    (("eligib", "rule", "matrix", "pricing", "tariff", "condition", "policy", "tier"),
     "Decision table / cause-effect"),
    (("flag", "parameter", "param", "role", "permission", "option", "combination"),
     "Pairwise (t-way) combinatorial"),
    (("depend", "integration", "external", "downstream", "service", "webhook", "queue"),
     "Error-path / fault injection"),
    (("money", "payment", "invoice", "auth", "security", "compliance", "gdpr", "audit", "refund"),
     "Risk-based depth"),
]
_DEFAULT_METHOD = "Equivalence Partitioning + Boundary Value Analysis"


def recommend_methods(pack: Pack) -> list[str]:
    """Suggest method(s) from the pack's shape — the signal->method map, EP+BVA always the base."""
    text = pack.summary_text().lower() if hasattr(pack, "summary_text") else ""
    matched = [method for keys, method in _SIGNALS if any(k in text for k in keys)]
    # EP+BVA is the base enumerator; keep it first, then the signal-matched methods (deduped, ordered).
    return list(dict.fromkeys([_DEFAULT_METHOD, *matched]))


class TestDesignRound(RoundQuestions):
    round = "test-design"

    def build(self, pack: Pack, primary: Note | None, title: str, q: QFactory) -> list[Question]:
        recommended = recommend_methods(pack)
        return [q(
            question=f"Which test-design method(s) should drive the cases for '{title}'? "
                     "(accept, change, or ADD any the pack can't infer)",
            why="The method decides how cases are enumerated toward 100% coverage; it is chosen from "
                "the feature's shape and the earlier methodology/scope/metrics decisions.",
            options=[{"label": m, "implication": impl} for m, impl in METHOD_OPTIONS],
            recommendation=" + ".join(recommended)
            + " — inferred from the pack; add security/performance/etc. if this feature needs them.",
            applies_to=primary.id if primary else pack.seed,
        )]
