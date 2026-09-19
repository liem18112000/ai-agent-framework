# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install the package incl. the [bridge] extra (mcp) and [gcp] extra (CloudProvider GCP adapter for
# KGA tiers 5/6/7 — inert at runtime until a cloud env matrix is configured). One image runs EITHER the
# agent (default CMD below) OR the A2A->MCP bridge service (override the command — see README).
COPY pyproject.toml ./
COPY src ./src
COPY main.py ./
# Phase C push-subscription worker entrypoint (uvicorn worker:app)
COPY worker.py ./
RUN pip install ".[bridge,gcp]"

# Run as non-root.
RUN useradd -m -u 10001 appuser
USER appuser

EXPOSE 8080
# Cloud Run injects $PORT. One image, one A2A entrypoint: main:app serves the agent named by $AGENT
# (knowledge_gathering | test_plan_definition | test_evaluation | testing_agent). The gateway service
# overrides this with `python -m gateway` (see deployments/test-agent-v2/services.tf).
CMD ["sh", "-c", "AGENT=${AGENT:-knowledge_gathering} uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
