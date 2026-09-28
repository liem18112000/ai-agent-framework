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
# Phase C worker entrypoints: worker.py (Pub/Sub HTTP push) + redis_worker.py (Redis Streams consumer)
COPY worker.py ./
COPY redis_worker.py ./
RUN pip install ".[bridge,gcp,jev,exec]"

# BrowserEngine (test_executor UI/E2E). Adds Playwright + chromium (+ its apt libs) — ~400MB shared
# across every agent image, so it is gated by a build arg (default on; `--build-arg INSTALL_BROWSER=false`
# for a lean build). Browsers go to a world-readable path so the non-root appuser finds them at runtime.
# Chromium needs root for its apt deps, so this runs BEFORE the USER switch.
ARG INSTALL_BROWSER=true
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN if [ "$INSTALL_BROWSER" = "true" ]; then \
      pip install ".[browser]" \
      && playwright install --with-deps chromium \
      && chmod -R a+rx /ms-playwright \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Run as non-root.
RUN useradd -m -u 10001 appuser
USER appuser

EXPOSE 8080
# Cloud Run injects $PORT. One image, one A2A entrypoint: main:app serves the agent named by $AGENT
# (knowledge_gathering | test_plan_definition | test_evaluation | testing_agent). The gateway service
# overrides this with `python -m gateway` (see deployments/test-agent-v2/services.tf).
CMD ["sh", "-c", "AGENT=${AGENT:-knowledge_gathering} uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
