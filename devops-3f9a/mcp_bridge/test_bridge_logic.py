"""Standalone sanity test for server.py's core logic, called directly
(not through the MCP stdio protocol) since Claude Code needs a restart
to pick up a new .mcp.json entry anyway.
"""

import server

print(server.ask_devops_agent("List GKE clusters in klara-nonprod"))
