# syntax=docker/dockerfile:1

FROM python:3-alpine AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache -r pyproject.toml


FROM python:3-alpine

WORKDIR /app

# Copy the entire Python install (packages + scripts) from the builder stage.
# Using /usr/local avoids fragile site-packages version path matching.
COPY --from=builder /usr/local/lib /usr/local/lib
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

COPY app/ ./app/
COPY web/ ./web/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
