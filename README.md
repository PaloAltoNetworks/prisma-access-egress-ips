# Prisma Access Egress IP Utility

[![license](https://img.shields.io/badge/License-PANW_PS-F04E23?logo=paloaltonetworks&logoSize=auto)](./LICENSE.md)
[![Build](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/actions/workflows/container.yml/badge.svg)](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/actions/workflows/container.yml)
[![ghcr](https://img.shields.io/badge/ghcr.io-latest-blue?logo=docker&logoColor=white)](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/pkgs/container/prisma-access-egress-ips)

A browser-based tool for looking up Prisma Access egress IP addresses. Runs as a single Docker container — enter your API key in the browser, select what you need, and export the results as CSV, JSON, or plain text. No credentials are stored server-side.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (includes Docker Compose)

## Quick Start

### Option A — Hosted image (recommended)

No clone required. Download the compose file and start the container:

```bash
curl -fsSLO https://raw.githubusercontent.com/PaloAltoNetworks/prisma-access-egress-ips/main/compose.yml
docker compose up -d
```

The image is published to the GitHub Container Registry and rebuilt weekly to pick up base-image security patches. To pin a specific release, replace `latest` with a SHA digest from the [package page](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/pkgs/container/prisma-access-egress-ips).

### Option B — Build from source

```bash
git clone https://github.com/PaloAltoNetworks/prisma-access-egress-ips.git
cd prisma-access-egress-ips
docker compose -f compose.build.yml up --build -d
```

Once running, open **<http://localhost:8000>**.

## Getting Your API Key

You need an **Egress IP API key** from your Prisma Access tenant. The steps depend on your management platform:

**Panorama managed**

Panorama tab > Cloud Services Plugin > Configuration > Service Setup > **Egress IP API**

**Strata Cloud Manager (SCM)**

Configuration > NGFW & Prisma Access > Prisma Access > Setup > **Egress IP API**

Copy the API key and paste it into the tool's **API Key** field.

## Using the Tool

1. **Paste your API key** into the API Key field (click the eye icon to verify it).
2. **Select your environment** from the dropdown (see [Environments](#environments) if unsure).
3. **Choose a mode:**
   - **Single** — query one node type at a time.
   - **Batch (all)** — query all node types at once. Optionally filter by location.
4. **Pick a node type** (Single mode) or leave the default (Batch mode).
5. **Click Query.**

Results appear in a table. From there you can:

- **Copy IPs** to clipboard
- **Download** as CSV, JSON, or TXT

> **Wrong environment?** If the API returns a `401`, the tool automatically retries against the other environments in parallel and updates the dropdown to whichever one accepted your key.

## Environments

| Key | Endpoint |
| ----- | ---------- |
| `prod1` | `api.prod.datapath.prismaaccess.com` |
| `prod4` | `api.prod4.datapath.prismaaccess.com` |
| `prod6` | `api.prod6.datapath.prismaaccess.com` |
| `prod8` | `api.prod8.datapath.prismaaccess.com` |
| `fedramp` | `api.fed.prismaaccess.com` |
| `lab` | `api.lab.datapath.prismaaccess.com` |

If you don't know which environment your tenant is on, just pick any — the auto-retry will find the right one.

## Node Types

| Key | Description | Notes |
| ----- | ------------- | ------- |
| `gw` | GlobalProtect Gateway (deployed) | Currently active gateways |
| `gw_all` | GlobalProtect Gateway (all) | Includes provisioned-but-not-yet-deployed |
| `gw_pre` | Gateway pre-allocated IPs | Exclusive — overlapping IPs from `gw_all` are subtracted |
| `pt` | GlobalProtect Portal (deployed) | |
| `rbi` | Remote Browser Isolation | |
| `rn` | Remote Network (deployed) | Currently active remote networks |
| `rn_all` | Remote Network (all) | Includes provisioned-but-not-yet-deployed |
| `swg` | SWG Proxy (deployed) | Exclusive — overlapping IPs from `swg_lb` are subtracted |
| `swg_lb` | SWG Network Load Balancer | |
| `swg_all` | SWG Proxy (all) | Exclusive — overlapping IPs from `swg_lb` are subtracted |
| `all` | Composite — every type, all locations | Batch query across everything |
| `all_deployed` | Composite — every type, deployed only | Batch query, active infrastructure only |

**Deployed vs. All:** "Deployed" returns IPs for infrastructure that is currently active. "All" also includes IPs that have been provisioned but are not yet in service.

**Exclusive lists:** `swg`, `swg_all`, and `gw_pre` subtract overlapping IPs from related types (`swg_lb` and `gw_all` respectively) so you get a clean, non-overlapping set.

## API Reference

The tool also exposes a REST API if you prefer to query programmatically.

| Method | Path | Description |
| -------- | ------ | ------------- |
| `POST` | `/api/ips/query` | Single node type query |
| `POST` | `/api/ips/batch` | All node types + composites |
| `POST` | `/api/ips/pre-allocate` | Pre-allocate Mobile User IPs |
| `GET`  | `/api/locations` | List Prisma Access locations (Bearer token) |
| `POST` | `/api/auth/token` | Exchange SASE client credentials for bearer token |
| `GET`  | `/health` | Health check |

Interactive API documentation is available at **<http://localhost:8000/api/docs>** once the container is running.

## Troubleshooting

**401 Unauthorized on every environment**
Your API key may be expired or invalid. Regenerate it from the Egress IP API page in Panorama or SCM.

**Container starts but the page won't load**
Check that port 8000 isn't already in use. To use a different port, edit the `ports` mapping in the compose file (e.g., `9000:8000` to use port 9000).

**Queries hang or time out**
The container needs outbound HTTPS access to `*.datapath.prismaaccess.com` (and `api.fed.prismaaccess.com` for FedRAMP). Ensure your firewall or proxy allows this traffic.

**Empty results for a node type**
Not all tenants have every service deployed. If a node type returns no results, that service may not be provisioned in your environment.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for architecture details, project structure, and local development setup.

## License

See [LICENSE.md](./LICENSE.md).
