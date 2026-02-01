FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency files first for Docker layer caching
COPY backend/pyproject.toml backend/uv.lock ./backend/

# Install dependencies
WORKDIR /app/backend
RUN uv sync --frozen --no-dev

# Copy application source
WORKDIR /app
COPY backend/ ./backend/
COPY bible_chunking/ ./bible_chunking/

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

WORKDIR /app/backend
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
