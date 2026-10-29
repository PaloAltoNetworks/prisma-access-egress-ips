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
├── Dockerfile                # Multi-stage build: Debian 13 + uv builder, distroless runtime
├── compose.yml               # Pre-built image compose file (end users)
├── compose.build.yml         # Build-from-source compose file
├── pyproject.toml            # Version source and dependency ranges
├── uv.lock                   # Locked dependency set used by CI and the image
├── CHANGELOG.md              # Release notes (Keep a Changelog)
├── docs/decisions/           # Recorded design decisions
├── tests/                    # pytest suite; gates the container build in CI
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

### Dependencies and Tests

Dependencies are managed with [uv](https://docs.astral.sh/uv/). `pyproject.toml` declares ranges and the committed `uv.lock` pins the exact set that CI and the image install (`uv sync --locked`). Dev tools go in the `dev` dependency group.

```bash
uv sync                # create .venv from uv.lock (Python 3.13, see .python-version)
uv run pytest          # run the test suite
uv lock                # re-resolve after editing pyproject.toml; commit uv.lock with it
```

CI also runs `pip-audit` against the locked runtime dependencies and fails on known vulnerabilities.

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

1. **Builder stage**: `debian:13-slim` with Debian's `python3.13` and a pinned `uv`. It runs `uv sync --locked --no-dev` into `/app/.venv`.
2. **Runtime stage**: `gcr.io/distroless/python3-debian13:nonroot`. No shell, no package manager, runs as UID 65532. A `HEALTHCHECK` probes `/health`.

All base images are pinned by digest and bumped together by Dependabot. [docs/decisions/0001-distroless-runtime.md](./docs/decisions/0001-distroless-runtime.md) explains why the runtime is distroless and why Python is 3.13.

Runtime command: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`

## CI and Releases

`.github/workflows/ci.yml` runs tests and `pip-audit` on every push and PR. The image build `needs:` the tests.

| Trigger | Image tags |
| ------- | ---------- |
| Push to a non-main branch | none (tests only) |
| Pull request | built, not pushed |
| Push to `main` | `:main`, `:sha-<short>` |
| Tag `vX.Y.Z` | `:X.Y.Z`, `:X.Y`, and `:latest` if it's the highest release |
| Weekly schedule | newest release rebuilt on fresh base images, same tags |

Versions follow [SemVer](https://semver.org). `pyproject.toml` is the only version source; the app reads it from package metadata.

**To release**, bump `version` in `pyproject.toml` in the PR, and in `CHANGELOG.md` turn `## [Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD`, leaving a fresh empty `[Unreleased]` above it. CI checks that a bumped version has a changelog section and isn't tagged yet. Once the PR is squash-merged, CI tags `vX.Y.Z` on `main` and dispatches the release build. That build checks the tag matches `pyproject.toml`, the changelog section exists and the commit is on `main`, then publishes the images and a GitHub release whose notes are the changelog section. PRs without a bump merge without releasing.

A repository ruleset stops anyone but admins from moving or deleting `v*` tags. Creating them is left open so CI can tag with `GITHUB_TOKEN`, which is safe because the release build only publishes a tag that passes the checks above.

## Git Workflow

Branch as `feat/<thing>` or `fix/<thing>`, one logical change per PR, squash merge. Branches are deleted on merge.

GitHub Actions are pinned by full commit SHA with the version as a comment, and must run on `node24`. Re-check an action's `runs.using` before merging a Dependabot major bump.

## Code Conventions

- **Node type keys** use underscores throughout (e.g., `gw_pre`, `rn_all`). The original CLI used mixed hyphens and underscores — all normalized here.
- **Exclusive lists** — `swg`, `swg_all`, and `gw_pre` subtract overlapping IPs from related types. This logic lives in `app/services/ip_processor.py`.
- **No environment variables by design** — the app is a stateless proxy. Configuration changes should go in `config.py`.
- **Frontend** — vanilla HTML/JS/CSS with no build step. Files in `web/` are served as static assets.

## History

Ported from the CLI tool `pa-ips.py` (v5.1). File I/O, argparse, and all local state were removed — everything is returned as JSON via the REST API.
