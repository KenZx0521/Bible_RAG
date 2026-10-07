# Empty fallback for the uv cache. docker compose overrides this stage with a
# host directory (build.additional_contexts.uvcache, see docker-compose.yml), so
# `uv sync` reuses already-downloaded wheels (torch + CUDA ~4 GB) instead of
# re-downloading them. A plain `docker build .` still works: the cache is just empty.
FROM scratch AS uvcache

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Pinned: a uv cache is only reusable by a uv that reads the same cache format.
# The seeded host cache (wheels-v6 / simple-v24) was written by uv 0.12.0.
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency files first for Docker layer caching
COPY backend/pyproject.toml backend/uv.lock ./backend/

# Install dependencies. The cache is mounted read-write but writes are discarded
# after this step (the host directory is never modified, the image carries no
# cache). UV_LINK_MODE=copy: a bind-mounted cache cannot be hardlinked into the layer.
WORKDIR /app/backend
RUN --mount=type=bind,from=uvcache,target=/root/.cache/uv,rw=true \
    UV_LINK_MODE=copy uv sync --frozen --no-dev

# Copy application source
WORKDIR /app
COPY backend/ ./backend/
COPY bible_chunking/ ./bible_chunking/
COPY scripts/ ./scripts/
# Shared contracts (ragcommon.encoder: pinned tokenizers). Imported through
# PYTHONPATH rather than a pyproject dependency, so uv.lock stays as is.
COPY packages/ragcommon/ ./packages/ragcommon/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/packages

EXPOSE 8000

WORKDIR /app/backend
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
