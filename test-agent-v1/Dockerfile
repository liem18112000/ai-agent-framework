# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install the package incl. the [bridge] extra (mcp), so this one image can run EITHER the
# agent (default CMD below) OR the A2A->MCP bridge service (override the command — see README).
COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[bridge]"

# Run as non-root.
RUN useradd -m -u 10001 appuser
USER appuser

EXPOSE 8080
# Cloud Run injects $PORT; the A2A ASGI app is knowledge_gathering.server:app (M0).
CMD ["sh", "-c", "uvicorn knowledge_gathering.server:app --host 0.0.0.0 --port ${PORT}"]
