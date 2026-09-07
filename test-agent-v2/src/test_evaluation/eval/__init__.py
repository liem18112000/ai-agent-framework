"""ADK-native evaluator (Plan B) — golden → evalsets, domain metrics as ADK custom metrics.

The v1 engine math is reused verbatim (engine.evaluate_pack / plan_engine.evaluate_plan); this layer
exposes it through google-adk's eval contract so `adk eval` (CI PR gate + nightly judged tier) runs
it and the runtime MCP tools share the same code. See docs/adk-transform/03-plan-test-evaluation.md.
"""

from test_evaluation.eval import adk_metrics, config, evalset, runner

__all__ = ["adk_metrics", "config", "evalset", "runner"]
