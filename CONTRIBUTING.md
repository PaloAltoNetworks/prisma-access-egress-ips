# Contributing

Development guide for the Prisma Access Egress IP Utility. For usage instructions, see [README.md](./README.md).

## Architecture

```text
Browser (static frontend)
  └─ POST /api/ips/query  { api_key, environment, node_type }
       ▼
  FastAPI worker (Python + httpx)
       └─ POST https://api.{env}.datapath.prismaaccess.com/getPrismaAccessIP/v2
              ▼
          Prisma Access Public API
```

The worker is a stateless authenticated proxy. API keys are passed per-request from the browser and never persisted. There are no databases, caches, or environment variables — all configuration is hardcoded in `app/config.py`.

## Project Structure

```text
.
├── Dockerfile                # Multi-stage build (python:3-alpine + uv)
├── compose.yml               # Pre-built image compose file (end users)
├── compose.build.yml         # Build-from-source compose file
├── pyproject.toml            # Python dependencies (FastAPI, httpx, uvicorn, pydantic)
├── app/
│   ├── main.py               # FastAPI app, static file serving, health check
│   ├── config.py             # API URLs, node type payloads, constants
│   ├── models.py             # Pydantic request/response models
│   ├── routers/
│   │   ├── ips.py            # /api/ips/* endpoints
│   │   ├── locations.py      # /api/locations
│   │   └── auth.py           # /api/auth/token
│   └── services/
│       ├── prisma_client.py  # Async Prisma Access API client (httpx)
│       └── ip_processor.py   # Business logic: normalize, subtract, merge, batch
└── web/
    ├── index.html            # Single-page frontend
    ├── app.js                # UI logic, API calls, export handlers
    └── style.css             # Styles
```

## Local Development

### Running with Docker (recommended)

```bash
docker compose -f compose.build.yml up --build
```

This builds the image from source and starts the container on port 8000 with live output.

### Regenerating the Lockfile

Dependencies are managed with [uv](https://docs.astral.sh/uv/). To regenerate `uv.lock` without installing anything on your host:

```bash
docker run --rm -v $(pwd):/app -w /app python:3-alpine \
  sh -c "pip install uv && uv lock"
```

### OpenAPI Docs

Once the container is running, interactive API documentation is available at:

- Swagger UI: <http://localhost:8000/api/docs>
- ReDoc: <http://localhost:8000/api/redoc>
- OpenAPI schema: <http://localhost:8000/api/openapi.json>

These are useful for testing individual endpoints without the frontend.

## Configuration

All runtime configuration lives in `app/config.py`:

| Constant | Purpose |
| -------- | ------- |
| `API_URLS` | Maps environment keys to Prisma Access API endpoints |
| `NODE_PAYLOADS` | Maps node type keys to API request bodies (`serviceType`, `addrType`, `location`) |
| `COMPONENTS_FOR_ALL` | Node types included in the `all` composite aggregate |
| `COMPONENTS_FOR_ALL_DEPLOYED` | Node types included in the `all_deployed` composite aggregate |
| `API_TIMEOUT_SECONDS` | Per-request timeout (30s) |
| `MAX_CONCURRENT_REQUESTS` | Concurrency limit for batch queries (10) |
| `MIN_REQUEST_INTERVAL` | Rate-limiting delay between requests (0.1s) |

There are no environment variables — this is intentional. The container is designed to be zero-config.

## Docker

The Dockerfile uses a multi-stage build:

1. **Builder stage** — installs `uv` and resolves Python dependencies from `pyproject.toml`.
2. **Runtime stage** — copies the Python install and application code into a clean `python:3-alpine` image.

The base image uses the `python:3-alpine` floating tag to track the latest Python 3.x patch. The GHCR image is rebuilt weekly via GitHub Actions to pick up security patches.

Runtime command: `uvicorn app.main:app --host 0.0.0.0 --port 8000`

## Code Conventions

- **Node type keys** use underscores throughout (e.g., `gw_pre`, `rn_all`). The original CLI used mixed hyphens and underscores — all normalized here.
- **Exclusive lists** — `swg`, `swg_all`, and `gw_pre` subtract overlapping IPs from related types. This logic lives in `app/services/ip_processor.py`.
- **No environment variables by design** — the app is a stateless proxy. Configuration changes should go in `config.py`.
- **Frontend** — vanilla HTML/JS/CSS with no build step. Files in `web/` are served as static assets.

## History

Ported from the CLI tool `pa-ips.py` (v5.1). File I/O, argparse, and all local state were removed — everything is returned as JSON via the REST API.
