# Prisma Access Egress IP Utility

[![license](https://img.shields.io/badge/License-PANW_PS-F04E23?logo=paloaltonetworks&logoSize=auto)](./LICENSE.md)
[![Build](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/actions/workflows/container.yml/badge.svg)](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/actions/workflows/container.yml)
[![image](https://ghcr-badge.egpl.dev/paloaltonetworks/prisma-access-egress-ips/latest_tag?trim=major&label=ghcr)](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/pkgs/container/prisma-access-egress-ips)

A web-based utility for querying Prisma Access egress IPs. Runs as a single Docker container — users provide their API key in the browser; no credentials are stored server-side.

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

The worker is a thin authenticated proxy. Tokens are passed per-request and never persisted.

## Running

### Hosted image (recommended)

No clone required. Copy [`docker-compose.ghcr.yml`](./docker-compose.ghcr.yml) and run:

```bash
docker compose -f docker-compose.ghcr.yml up -d
```

The image is published to GHCR and rebuilt weekly to pick up base image security patches. To pin to a specific release, replace `latest` with a SHA digest from the [package page](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/pkgs/container/prisma-access-egress-ips).

### Build from source

```bash
docker compose up --build -d
```

Open `http://localhost:8000`.

## API Endpoints

| Method | Path | Description |
| -------- | ------ | ------------- |
| `POST` | `/api/ips/query` | Single node type query |
| `POST` | `/api/ips/batch` | All node types + composites |
| `POST` | `/api/ips/pre-allocate` | Pre-allocate Mobile User IPs |
| `GET`  | `/api/locations` | List Prisma Access locations (Bearer token) |
| `POST` | `/api/auth/token` | Exchange SASE client credentials for bearer token |
| `GET`  | `/api/docs` | Interactive OpenAPI docs |
| `GET`  | `/health` | Health check |

## Node Types

| Key | Description |
| ----- | ------------- |
| `gw` | GlobalProtect Gateway (deployed) |
| `gw_all` | GlobalProtect Gateway (all) |
| `gw_pre` | Gateway pre-allocated IPs |
| `pt` | GlobalProtect Portal (deployed) |
| `rbi` | Remote Browser Isolation |
| `rn` | Remote Network (deployed) |
| `rn_all` | Remote Network (all) |
| `swg` | SWG Proxy (deployed, exclusive of LB IPs) |
| `swg_lb` | SWG Network Load Balancer |
| `swg_all` | SWG Proxy (all, exclusive of LB IPs) |
| `all` | Composite — all types, all locations |
| `all_deployed` | Composite — all types, deployed only |

Note: `swg`, `swg_all`, and `gw_pre` are exclusive lists — overlapping IPs from `swg_lb` / `gw_all` are subtracted server-side, matching the behaviour of the original CLI tool.

## Environments

| Key | Endpoint |
| ----- | ---------- |
| `prod1` | `api.prod.datapath.prismaaccess.com` |
| `prod4` | `api.prod4.datapath.prismaaccess.com` |
| `prod6` | `api.prod6.datapath.prismaaccess.com` |
| `prod8` | `api.prod8.datapath.prismaaccess.com` |
| `fedramp` | `api.fed.prismaaccess.com` |
| `lab` | `api.lab.datapath.prismaaccess.com` |

If you select the wrong environment, the app detects the `401` and automatically retries against the remaining environments in parallel, then updates the selector to show which one accepted your key.

## Project Structure

```text
.
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── app/
│   ├── main.py               # FastAPI app, static file serving
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
    ├── index.html
    ├── app.js
    └── style.css
```

## Development Notes

- Base image: `python:3-alpine` (floating tag — tracks latest Python 3.x patch)
- Dependencies managed with `uv`; to generate a lockfile without touching the host:

  ```bash
  docker run --rm -v $(pwd):/app -w /app python:3-alpine \
    sh -c "pip install uv && uv lock"
  ```

- The OpenAPI docs at `/api/docs` are useful for testing individual endpoints directly
- Ported from CLI tool `pa-ips.py` (v5.1); file I/O and argparse removed, all output returned as JSON
