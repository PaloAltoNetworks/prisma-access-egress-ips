# Contributing

Development guide for the Prisma Access Egress IP Utility. For usage instructions, see [README.md](./README.md).

## Architecture

```text
Browser (static frontend, web/)
  │  API key or SASE client credentials, per request
  ▼
FastAPI worker (app/, Python + httpx)
  ├─ POST /api/ips/*        → POST the selected environment's endpoint (API_URLS in app/config.py)
  │                           (on 401 from a commercial environment, probes the other commercial
  │                           environments in parallel; FedRAMP environments are never probed)
  ├─ POST /api/auth/token   → POST https://auth.apps.paloaltonetworks.com/oauth2/access_token
  └─ GET  /api/locations    → GET  https://api.sase.paloaltonetworks.com/sse/config/v1/locations
```

The worker is a stateless proxy. Credentials arrive with each request and leave with the response; nothing is persisted. There are no databases or caches, and all configuration is in `app/config.py`. The only environment variables honoured are the standard proxy settings (`HTTPS_PROXY`, `NO_PROXY`, `ALL_PROXY`, upper or lower case), which httpx reads.

**The web page is the only supported interface.** The `/api/...` endpoints exist to serve it: they're not documented for users, publish no OpenAPI schema, and can change in any release without a version bump to signal it. Users who want to automate lookups call the Prisma Access egress IP API directly. `/api/auth/token` and `/api/locations` are kept for UI features that use SASE credentials.

## Engineering Principles

These are the maintainers' engineering standards for this repository. Read them before changing the code, CI, the Dockerfile or dependencies.

- **Right-size it.** One stateless container. Anything that stores data is a design change; raise an issue first.
- **Secrets never go in git, images or logs.** Never log a request body, header or token.
- **Secrets only travel over verified TLS.** Never fall back to an unverified connection automatically. Users behind SSL decryption mount their organization's CA ([docs/custom-ca.md](./docs/custom-ca.md)). The one exception is a certificate the user approves after seeing the failing chain: the top CA for an untrusted issuer (hostname and expiry still checked), or that exact leaf for that host for any other failure. Approvals last for the browser session only and are sent with each request; the server keeps no state.
- **The server is authoritative.** Request models forbid unknown fields (`model_config = ConfigDict(extra="forbid")`) and bound string lengths. Client-side checks are only there for UX.
- **Escape by construction.** In the browser, build the DOM with `textContent` and `createElement`, not `innerHTML` with interpolated values. Treat data from the Prisma Access API as untrusted too.
- **Minimal dependencies.** Each one is a decision. Prefer the standard library and what FastAPI already brings.
- **Comments say why, in one or two lines.** No history, dates or personal context in code, issues, PRs or commits. This repository is public.

## Project Structure

```text
.
├── .github/
│   ├── workflows/ci.yml      # Tests, audit, image build and release automation
│   ├── scripts/release.py    # Version and changelog checks used by CI
│   └── dependabot.yml        # Weekly grouped updates: actions, docker, uv
├── Dockerfile                # Multi-stage build: Debian 13 + uv builder, distroless runtime
├── .dockerignore             # Allowlist of what reaches the build context
├── compose.yml               # Pre-built image compose file (end users)
├── compose.build.yml         # Build-from-source compose file
├── pyproject.toml            # Version source and dependency ranges
├── uv.lock                   # Locked dependency set used by CI and the image
├── .python-version           # Python minor for local dev and CI (matches the image)
├── CHANGELOG.md              # Release notes (Keep a Changelog)
├── SECURITY.md               # How to report vulnerabilities
├── docs/                     # User guides (deployment, reference, custom CA) and decisions/
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
│       ├── prisma_client.py  # Async client for the Prisma Access, SASE and OAuth APIs
│       ├── tls.py            # Verified TLS context, custom CA loading, certificate errors
│       └── ip_processor.py   # Business logic: normalize, subtract, merge, batch
└── web/
    ├── index.html            # Single-page frontend
    ├── app.js                # UI logic, API calls, export handlers
    └── style.css             # Styles
```

## Local Development

### Running Locally

With [uv](https://docs.astral.sh/uv/) (fastest iteration, auto-reload):

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Or build and run the production image:

```bash
docker compose -f compose.build.yml up --build
```

Either way the app is on <http://localhost:8000>.

### Dependencies

`pyproject.toml` declares ranges and the committed `uv.lock` pins the exact set that CI and the image install (`uv sync --locked`). Dev tools such as pytest go in the `dev` dependency group, never in runtime dependencies.

```bash
uv add <package>          # add a runtime dependency (updates pyproject.toml and uv.lock)
uv add --dev <package>    # add a dev-only tool
uv lock                   # re-resolve after editing pyproject.toml by hand
```

Commit `uv.lock` with any dependency change. CI runs `pip-audit` against the locked runtime set and fails on known vulnerabilities. Dependabot opens weekly grouped update PRs, and opens security updates as soon as an advisory lands.

### Tests

```bash
uv run pytest
```

Tests must not reach the real Prisma Access, SASE or OAuth APIs. Mock them with `httpx.MockTransport`. Add tests with any change to `ip_processor.py` logic, request validation or error handling.

## Configuration

All runtime configuration lives in `app/config.py`:

| Constant | Purpose |
| -------- | ------- |
| `API_URLS` | Maps environment keys to Prisma Access API endpoints |
| `LOCATIONS_API_URL` | SASE Config API endpoint for Prisma Access locations |
| `OAUTH_TOKEN_URL` | OAuth endpoint that exchanges SASE client credentials for a bearer token |
| `CUSTOM_CA_DIR` | Directory (`/certs`) whose `*.pem` / `*.crt` files are trusted alongside the public roots |
| `NODE_PAYLOADS` | Maps node type keys to API request bodies (`serviceType`, `addrType`, `location`) |
| `COMPONENTS_FOR_ALL` | Node types included in the `all` composite aggregate |
| `COMPONENTS_FOR_ALL_DEPLOYED` | Node types included in the `all_deployed` composite aggregate |
| `API_TIMEOUT_SECONDS` | Per-request timeout (30s) |
| `MAX_CONCURRENT_REQUESTS` | Concurrency limit for batch queries (10) |
| `MIN_REQUEST_INTERVAL` | Rate-limiting delay between requests (0.1s) |

There are no app-specific environment variables by design; the container is zero-config. httpx honours the standard `HTTPS_PROXY` / `NO_PROXY` variables for users behind an explicit proxy.

## Docker

The Dockerfile uses a multi-stage build:

1. **Builder stage**: `debian:13-slim` with Debian's `python3.13` and a pinned `uv`. It runs `uv sync --locked --no-dev` into `/app/.venv`.
2. **Runtime stage**: `gcr.io/distroless/python3-debian13:nonroot`. No shell, no package manager, runs as UID 65532. A `HEALTHCHECK` probes `/health`.

All base images are pinned by digest and bumped together by Dependabot. [docs/decisions/0001-distroless-runtime.md](./docs/decisions/0001-distroless-runtime.md) explains why the runtime is distroless and why Python is 3.13. Keep the Python minor the same in `requires-python`, `.python-version` and the image.

The image has no shell. To inspect a running container, use its Python: `docker exec <id> /app/.venv/bin/python -c "..."`.

Both compose files run the container read-only with a `/tmp` tmpfs, all capabilities dropped and `no-new-privileges`. Keep the app compatible with that: don't write outside `/tmp`.

## CI and Releases

`.github/workflows/ci.yml` runs tests and `pip-audit` on every push and PR. The image build `needs:` the tests.

| Trigger | Image tags |
| ------- | ---------- |
| Push to a non-main branch | none (tests only) |
| Pull request | built, not pushed |
| Push to `main` | `:main`, `:sha-<short>` |
| Tag `vX.Y.Z` | `:X.Y.Z`, `:X.Y`, `:X` if it's the highest release in `X`, and `:latest` if it's the highest release |
| Weekly schedule | newest release rebuilt on fresh base images, same release tags (`:main` and `:sha-…` untouched) |
| Manual run on a branch | `:dev`, `:sha-<short>` of the branch head |

**To hand a branch to a tester**, a maintainer runs `gh workflow run ci.yml --ref <branch>` (or **Run workflow** on the CI workflow's Actions page). It runs the tests, then publishes the branch as `:dev` and `:sha-<short>`. `:dev` is whichever branch was published last, so give testers the `:sha-…` tag when more than one branch is under test. Running it on `main` is refused, because `main` is already published as `:main`.

Versions follow [SemVer](https://semver.org). The supported interface is the web page and the compose files: MAJOR when users have to change something there, MINOR for features, PATCH for fixes. The internal `/api/...` endpoints aren't part of it. `pyproject.toml` is the only version source; the app reads it from package metadata.

**To release**, bump `version` in `pyproject.toml` in the PR, and in `CHANGELOG.md` turn `## [Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD`, leaving a fresh empty `[Unreleased]` above it. CI checks that a bumped version has a changelog section and isn't tagged yet. Once the PR is squash-merged, CI tags `vX.Y.Z` on `main` and dispatches the release build. That build checks the tag matches `pyproject.toml`, the changelog section exists and the commit is on `main`, then publishes the images and a GitHub release whose notes are the changelog section, with `compose.yml` attached for the Quick Start. PRs without a bump merge without releasing.

A repository ruleset stops anyone but admins from moving or deleting `v*` tags. Creating them is left open so CI can tag with `GITHUB_TOKEN`, which is safe because the release build only publishes a tag that passes the checks above.

GitHub Actions are pinned by full commit SHA with the version as a comment, and must run on `node24`. Re-check an action's `runs.using` before merging a Dependabot major bump.

## Pull Requests

- Branch as `feat/<thing>` or `fix/<thing>`. One logical change per PR. PRs are squash-merged, and the PR title and description become the commit on `main`. Branches are deleted on merge.
- Add a line under `## [Unreleased]` in `CHANGELOG.md` for anything users would notice, written for the people who run the tool.
- `uv run pytest` passes, and `uv.lock` is committed if dependencies changed.
- Report security vulnerabilities privately, not in a public issue or PR.

### Reviews

When a review (human or AI) reports findings, verify each one against the code before acting. Give it a verdict (confirmed, partly or wrong) with evidence. Fix confirmed High and Medium findings in the same PR and file the rest as issues. There is one review round; after that, only High or data-exposure findings block a merge.

## Code Conventions

- **Node type keys** use underscores throughout (e.g., `gw_pre`, `rn_all`).
- **Exclusive lists**: `swg`, `swg_all` and `gw_pre` subtract overlapping IPs from related types. This logic lives in `app/services/ip_processor.py`.
- **Frontend**: vanilla HTML/JS/CSS with no build step. Files in `web/` are served as static assets.

## History

Ported from the CLI tool `pa-ips.py` (v5.1). File I/O, argparse and all local state were removed, and everything is returned as JSON via the REST API.
