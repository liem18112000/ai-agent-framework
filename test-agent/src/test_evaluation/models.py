"""Data model for the evaluation agent — the golden EvalCase, the scored EvalReport, and every
metric result as a typed dataclass (no bare dicts crossing module boundaries).

Only genuinely dynamic, variable-key mappings stay dicts: the WEIGHTS / SEMANTIC_RUBRICS config
tables, and HistoryRecord.per_seed (a seed-id → scores map).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields


# --- golden spec + top-level report --- #
@dataclass
class EvalCase:
    """One golden seed — the human-curated ground truth a pack is scored against."""

    seed: str
    fixture: str = ""
    depth: int = 1
    shape: str = ""
    expected_trajectory: list[str] = field(default_factory=list)
    expected_tiers: list[str] = field(default_factory=list)
    expected_fetch_kinds: list[str] = field(default_factory=list)
    relevant_node_ids: list[str] = field(default_factory=list)
    must_not_retrieve_ids: list[str] = field(default_factory=list)
    key_entities: list[str] = field(default_factory=list)
    min_recall: float = 0.8
    min_precision: float = 0.7
    reference_understanding: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> EvalCase:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


# --- metric results --- #
@dataclass
class RetrievalScore:
    """RAGAS Context Precision/Recall/F1 by node-id set overlap + the hard-negative leak gate."""

    precision: float
    recall: float
    f1: float
    leaked: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass
class EntitiesScore:
    """Context Entities Recall — which golden key-entities the pack's text surfaced."""

    recall: float
    found: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass
class PQSComponents:
    """The five surface scores that feed the Pack Quality Score (field names == WEIGHTS keys)."""

    faithfulness: float = 0.0
    ctx_precision: float = 0.0
    ctx_recall: float = 0.0
    relevancy: float = 0.0
    trajectory: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class PQSResult:
    """The weighted composite, always carrying its components."""

    pqs: float
    components: PQSComponents


@dataclass
class NoiseScore:
    """Output-level noise sensitivity — did the understanding absorb injected noise (0 = ignored)."""

    noise_sensitivity: float
    leaked_terms: list[str] = field(default_factory=list)


@dataclass
class RubricResult:
    """A pass/fail fabrication rubric with the offending items (`passed`, not `pass` — reserved)."""

    passed: bool
    invented: list[str] = field(default_factory=list)


@dataclass
class SemanticRubricResult:
    """The LLM-judged semantic rubrics (names-the-AC, gaps-honesty)."""

    names_the_ac: bool = False
    declares_gaps_honestly: bool = False


@dataclass
class RagasScore:
    """RAGAS generation metrics over the understanding (LLM-judged)."""

    faithfulness: float = 0.0
    answer_relevancy: float = 0.0


@dataclass
class RubricsReport:
    """The pack's fabrication-rubric verdicts."""

    cites_only_real_ids: RubricResult
    no_invented_urls: RubricResult


@dataclass
class HistoryRecord:
    """One nightly run persisted to the trend history. `per_seed` stays a dict (dynamic seed map)."""

    timestamp: str
    commit: str
    pqs: float
    components: dict = field(default_factory=dict)
    per_seed: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> HistoryRecord:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class EvalReport:
    """The scored result for one pack/context — the PQS plus every component that fed it."""

    context_id: str
    seed: str = ""
    pqs: float = 0.0
    components: PQSComponents = field(default_factory=PQSComponents)
    retrieval: RetrievalScore | None = None
    entities: EntitiesScore | None = None
    rubrics: RubricsReport | None = None
    tiers: list[str] = field(default_factory=list)


# ============================================================================
# TPD (test-plan) evaluation — the downstream twin: score the Test-Plan agent's
# plan + suite into a Test-Plan Score (TPS). Design: docs/RESEARCH-tpd-evaluation-adk-testsuite.md.
# ============================================================================


@dataclass
class PlanEvalCase:
    """One golden pack — the human-curated ground truth a plan+suite is scored against.

    `behaviours` stays a list of dicts (variable per-behaviour shape:
    {id, expected_partitions:[...], fault_classes:[...]})."""

    seed: str
    fixture: str = ""
    depth: int = 1
    shape: str = ""
    expected_trajectory: list[str] = field(default_factory=list)
    expected_rounds: list[str] = field(default_factory=list)
    in_scope_ids: list[str] = field(default_factory=list)
    must_not_scope_ids: list[str] = field(default_factory=list)
    behaviours: list[dict] = field(default_factory=list)
    pass_criteria: list[str] = field(default_factory=list)
    min_ac_recall: float = 0.8
    min_scope_precision: float = 0.8
    reference_brief: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> PlanEvalCase:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    def behaviour_ids(self) -> list[str]:
        return [b["id"] for b in self.behaviours if "id" in b]


# Plan-scope Precision/Recall/F1 + the must_not_scope leak gate is field-identical to retrieval
# scoring, so scope reuses `RetrievalScore` (precision/recall/f1/leaked/missing) rather than a
# parallel dataclass — `leaked` is the define-brief-scoping bug guard.


@dataclass
class CoverageScore:
    """Coverage adequacy: AC-coverage recall + coverage-matrix completeness + traceability.
    `per_behaviour` stays a dict (behaviour-id -> fraction of required partitions present)."""

    ac_recall: float
    matrix_completeness: float
    traceability: float
    per_behaviour: dict = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)
    untraceable: list[str] = field(default_factory=list)


@dataclass
class OracleScore:
    """Oracle-strength distribution over the steps' `expected` (deterministic proxy for mutation).
    score = weighted mean (strong=1.0, medium=0.5, weak=0.0). `distribution` stays a small dict."""

    score: float
    distribution: dict = field(default_factory=dict)
    weak: list[str] = field(default_factory=list)


@dataclass
class PlaceholderReport:
    """Placeholder-leak + which-path provenance. A `detail` run that leaked a token or shipped a
    heuristic `_KIND_SUFFIX` title has silently fallen back to the heuristic."""

    passed: bool
    leaked_tokens: list[str] = field(default_factory=list)
    provenance: str = "unknown"  # llm | heuristic | mixed | unknown


@dataclass
class GherkinReport:
    """BDD/Gherkin lint over the exported .feature (deterministic tier: tag hygiene + structure)."""

    passed: bool
    scenarios: int = 0
    tagged: int = 0
    issues: list[str] = field(default_factory=list)


@dataclass
class FaultClassScore:
    """Fault-class-coverage proxy for mutation (gated on the execution stage). Of the golden
    behaviours' known fault classes, how many have a scenario aimed at them."""

    coverage: float
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass
class TPSComponents:
    """The five surface scores that feed the Test-Plan Score (field names == TPS_WEIGHTS keys)."""

    fault_detection: float = 0.0
    brief_groundedness: float = 0.0
    coverage: float = 0.0
    oracle_strength: float = 0.0
    trajectory: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class TPSResult:
    """The weighted composite, always carrying its components."""

    tps: float
    components: TPSComponents


@dataclass
class PlanReport:
    """The scored result for one plan+suite — the TPS plus every component that fed it."""

    context_id: str
    seed: str = ""
    tps: float = 0.0
    components: TPSComponents = field(default_factory=TPSComponents)
    scope: RetrievalScore | None = None  # scope reuses the retrieval score shape (see note above)
    coverage: CoverageScore | None = None
    oracle: OracleScore | None = None
    placeholders: PlaceholderReport | None = None
    gherkin: GherkinReport | None = None
    fault: FaultClassScore | None = None
    rubrics: RubricsReport | None = None
