# syntax=docker/dockerfile:1

# Distroless runtime with a matching Debian 13 builder; see docs/decisions/0001-distroless-runtime.md.
# Base images are pinned by digest and bumped together by Dependabot.

FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv

FROM debian:13-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4 AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3.13 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_PYTHON=/usr/bin/python3.13 \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first so source edits don't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY app/ ./app/
COPY web/ ./web/
RUN uv sync --locked --no-dev


FROM gcr.io/distroless/python3-debian13:nonroot@sha256:1c32c3720dc4c7f0c7dbe998737f32c200add6511eca7cec705008be488b87d6

WORKDIR /app

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# distroless nonroot
USER 65532:65532

EXPOSE 8000

# No curl/wget in distroless, so probe with the venv's Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

ENTRYPOINT ["/app/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
