# syntax=docker/dockerfile:1
# Local-Claude-subscription proxy: the `claude` CLI behind an OpenAI-compatible endpoint (server.py).
# Python base (matches the codebase) — Node is not needed since claude comes from the official installer.
FROM python:3.12-slim
# Use the OFFICIAL installer, NOT `npm i -g @anthropic-ai/claude-code`: the npm package's native binary
# fails in a slim container (postinstall/optional-dep issues → the `claude` bin is an error stub, and the
# platform binary Bus-errors). install.sh drops a working binary in ~/.local/bin.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL https://claude.ai/install.sh | bash \
 && ln -sf /root/.local/bin/claude /usr/local/bin/claude
WORKDIR /app
COPY claude_proxy/server.py ./server.py
ENV PORT=8088
EXPOSE 8088
CMD ["python", "server.py"]
