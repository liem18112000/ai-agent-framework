import vertexai
from vertexai import agent_engines

vertexai.init(project="klara-nonprod", location="us-central1")
engine = agent_engines.get(
    "projects/335505349498/locations/us-central1/reasoningEngines/5955858224837033984"
)

for event in engine.stream_query(
    user_id="smoke-test", message="List GKE clusters in klara-nonprod"
):
    print(event)
