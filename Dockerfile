# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.13.8 AS uv
FROM python:3.12-slim-bookworm AS base

COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    RUFF_CACHE_DIR=/tmp/ruff-cache

WORKDIR /app
RUN useradd --uid 10001 --create-home app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY app ./app
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS development
USER root
RUN uv sync --locked
COPY tests ./tests
USER app

FROM base AS runtime
