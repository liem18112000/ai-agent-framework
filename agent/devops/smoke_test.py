import vertexai
from vertexai import agent_engines

from mcp_bridge.config import LOCATION, PROJECT_ID, RESOURCE_NAME

vertexai.init(project=PROJECT_ID, location=LOCATION)
engine = agent_engines.get(RESOURCE_NAME)

for event in engine.stream_query(
    user_id="smoke-test", message="List GKE clusters in klara-nonprod"
):
    print(event)
