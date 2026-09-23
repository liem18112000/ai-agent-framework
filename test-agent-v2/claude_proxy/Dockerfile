# syntax=docker/dockerfile:1
# The local-Claude-subscription proxy: the `claude` CLI behind an OpenAI-compatible endpoint.
FROM node:20-slim
# Use the OFFICIAL installer, NOT `npm i -g @anthropic-ai/claude-code`: the npm package's native binary
# fails to install in a slim container (postinstall/optional-dep issues → the `claude` bin is only an
# error stub, and the platform binary Bus-errors). install.sh drops a working binary in ~/.local/bin.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL https://claude.ai/install.sh | bash \
 && ln -sf /root/.local/bin/claude /usr/local/bin/claude
WORKDIR /app
COPY claude_proxy/server.js ./server.js
ENV PORT=8088
EXPOSE 8088
CMD ["node", "server.js"]
