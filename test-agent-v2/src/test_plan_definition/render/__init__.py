"""Executable-artifact export (optional): render structured scenarios/steps to BDD Gherkin.

Distinct from memory/render.py (which renders the memory-bank markdown): this turns the
structured scenarios/steps — the source of truth — into runnable .feature files for the
downstream Test execution stage.
"""

from test_plan_definition.render.gherkin import export_features, render_feature

__all__ = ["export_features", "render_feature"]
