# syntax=docker/dockerfile:1

FROM python:3.11-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_PYTHON=/usr/local/bin/python3 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    NODE_ENV=production

# Install Node.js and npm so MCP servers launched via `npx` can run
RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

# Optional sanity check during build
RUN node --version && npm --version && npx --version

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-cache

COPY . .

# Create directories that your MCP filesystem server can safely expose
RUN mkdir -p /workspace /tmp

# Use the synced venv directly so startup does not re-run `uv`
ENTRYPOINT ["/app/.venv/bin/python", "main.py"]