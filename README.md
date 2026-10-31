# Prisma Access Egress IP Utility

[![CI](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/actions/workflows/ci.yml?query=branch%3Amain)
[![Release](https://img.shields.io/github/v/release/PaloAltoNetworks/prisma-access-egress-ips?sort=semver)](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/releases/latest)
[![Container](https://img.shields.io/badge/ghcr.io-image-2496ED?logo=docker&logoColor=white)](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/pkgs/container/prisma-access-egress-ips)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2FPaloAltoNetworks%2Fprisma-access-egress-ips%2Fmain%2Fpyproject.toml&logo=python&logoColor=white)](./pyproject.toml)
[![License](https://img.shields.io/badge/License-PANW_PS-F04E23?logo=paloaltonetworks&logoSize=auto)](./LICENSE.md)

A browser-based tool for looking up Prisma Access egress IP addresses. It runs as a single Docker container on your machine: enter your API key in the browser, pick what you need, and export the results as CSV, JSON or plain text. Nothing is stored server-side.

## Quick Start

You need [Docker](https://docs.docker.com/get-docker/) with Docker Compose.

```bash
curl -fsSLO https://github.com/PaloAltoNetworks/prisma-access-egress-ips/releases/latest/download/compose.yml
docker compose up -d
```

Open **<http://localhost:8000>**.

This runs the newest release and listens only on your machine. To pin a release, change the port, run it for a team, or build from source, see [Deployment](./docs/deployment.md).

## Getting Your API Key

You need an **Egress IP API key** from your Prisma Access tenant:

- **Panorama managed:** Panorama tab > Cloud Services Plugin > Configuration > Service Setup > **Egress IP API**
- **Strata Cloud Manager:** Configuration > NGFW & Prisma Access > Prisma Access > Setup > **Egress IP API**

## Using the Tool

1. Paste your API key into the **API Key** field.
2. Pick your **environment**. For a commercial tenant, if you're not sure, pick any commercial environment: when the key is rejected, the tool tries the other commercial environments and switches to the one that accepts it. For a FedRAMP tenant, select **FedRAMP Moderate** or **FedRAMP High**: FedRAMP environments are never searched.
3. Choose **Single** to query one node type, or **Batch (all)** to query every node type at once.
4. In Single mode, pick a **node type**. For `gw_pre`, you can enter a location to pre-allocate Mobile User IPs there.
5. Click **Query**, then copy the IPs or download them as CSV, JSON or TXT.

Environments and node types are described in the [Reference](./docs/reference.md).

## Troubleshooting

**401 Unauthorized on every environment**
If this is a FedRAMP key, select the FedRAMP environment: FedRAMP environments aren't searched. Otherwise your API key may be expired or invalid. Regenerate it from the Egress IP API page in Panorama or Strata Cloud Manager.

**The page won't load**
Check that nothing else is using port 8000, or [change the port](./docs/deployment.md#changing-the-port).

**Certificate verification failed**
Your network probably decrypts TLS traffic. Give the container your organization's CA certificate: see [Trusting a custom CA](./docs/custom-ca.md).

**Queries hang or time out**
The container needs outbound HTTPS to the Prisma Access APIs. See [Network access](./docs/deployment.md#network-access) for the hosts to allow.

**Empty results for a node type**
Not every tenant has every service deployed. An empty result usually means that service isn't provisioned.

## Documentation

- [Deployment](./docs/deployment.md): image tags and pinning, ports, network access, team use, building from source
- [Reference](./docs/reference.md): environments, node types, scripting
- [Trusting a custom CA](./docs/custom-ca.md): running behind SSL decryption
- [Changelog](./CHANGELOG.md) and [Releases](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/releases)
- [Contributing](./CONTRIBUTING.md)

## License and Support

This tool is provided under the Palo Alto Networks Script Software Agreement in [LICENSE.md](./LICENSE.md), as is and without support from Palo Alto Networks. Bug reports and suggestions are welcome as [GitHub issues](https://github.com/PaloAltoNetworks/prisma-access-egress-ips/issues). Report security vulnerabilities privately, as described in [SECURITY.md](./SECURITY.md).
