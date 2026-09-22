"""Self-exploration engine — the pre-crawl fan-out tiers and the G5 explore loop.

`executor` dispatches A2A skills and calls into this package for the knowledge
expansion phases; the dependency direction is one-way (`executor → explore →
{common, loop}`) — nothing under `explore` imports from `knowledge_gathering.executor`.
"""
