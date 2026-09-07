"""Shared engine for the Testing-Agent packages.

The generic, agent-agnostic core both agents build on: data contracts (`models`),
the GCS memory bank (`memory`), the interrogation/refine engine (`refine`), the
Claude-on-Vertex LLM surface (`llm`), the A2A->MCP bridge client (`bridge`), the
bearer-auth middleware (`middlewares`), executor helpers (`executor`), and a
toggleable logger (`monitoring`).

`knowledge_gathering` (crawler) and `test_plan_definition` (plan) both depend on
`common`; neither reaches into the other.
"""

__version__ = "0.1.0"
