"""Test-Plan Definition agent (test_plan_definition).

Step 3+4 of the Testing Agent: turn an approved insight pack (the "Collect insight"
hand-off from `knowledge_gathering`) into a confirmed Test Plan, then generate its test
data / scenarios / steps. Mirrors the `knowledge_gathering` skeleton — an A2A agent over
the shared GCS memory bank, driven by local Claude — but runs reconfirm -> generate
(define multi-turn, then implement one-shot) where gather ran generate -> reconfirm.

See docs/PROPOSAL-TEST-PLAN-DEFINITION.md for the module map. The A2A ASGI app is
`test_plan_definition.server:app`.
"""

__version__ = "0.1.0"
