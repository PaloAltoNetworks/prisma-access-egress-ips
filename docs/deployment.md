# Deployment

The [Quick Start](../README.md#quick-start) covers the default setup: the hosted image, newest
release, listening only on your machine. This page covers everything else.

## Image tags

Images are published to the GitHub Container Registry for `linux/amd64` and `linux/arm64`:
`ghcr.io/paloaltonetworks/prisma-access-egress-ips`.

| Tag | Tracks |
| --- | ------ |
| `:latest` | Newest release |
| `:0.1` | Newest `0.1.x` patch release |
| `:0.1.0` | One exact release |
| `:main` | Unreleased `main` branch, for testing only |

Every week the newest release is rebuilt on fresh base images to pick up OS security patches. Its
tags keep the same version but get a new digest. Older releases are not rebuilt. See the
[Changelog](../CHANGELOG.md) for what each release changed.

### Pinning a release

For anything beyond trying the tool, pin a release line in `compose.yml` so updates are
deliberate:

```yaml
services:
  app:
    image: ghcr.io/paloaltonetworks/prisma-access-egress-ips:0.1
```

`:0.1` gets patch releases and the weekly rebuild; `:0.1.0` never changes version. Then
`docker compose pull && docker compose up -d` updates within that line.

## Changing the port

The `ports` mapping in `compose.yml` is `host address:host port:container port`. To use port 9000:

```yaml
    ports:
      - "127.0.0.1:9000:8000"
```

Then open <http://localhost:9000>.

## Network access

The container makes outbound HTTPS (port 443) connections only. Allow these hosts through your
firewall or proxy:

| Host | Used for |
| ---- | -------- |
| `api.prod.datapath.prismaaccess.com`, `api.prod4.…`, `api.prod6.…`, `api.prod8.…`, `api.lab.datapath.prismaaccess.com` | Egress IP API, by environment |
| `api.fed.prismaaccess.com` | Egress IP API, FedRAMP |
| `api.sase.paloaltonetworks.com` | Prisma Access locations |
| `auth.apps.paloaltonetworks.com` | OAuth tokens for the locations API |

If your network decrypts TLS, see [Trusting a custom CA](./custom-ca.md).

## Running it for a team

By default the container listens only on `127.0.0.1`, so only the machine running it can reach it.
That's deliberate. The tool has no login of its own, and the browser sends API keys to the
container over plain HTTP.

To share it, don't just change the binding to `0.0.0.0`. Put it behind a reverse proxy that
terminates TLS and controls who can reach it, such as your existing ingress, a load balancer or
an SSO proxy, and keep the container itself unreachable from anywhere else. Each user still
enters their own API key; nothing is stored between requests.

## Building from source

```bash
git clone https://github.com/PaloAltoNetworks/prisma-access-egress-ips.git
cd prisma-access-egress-ips
docker compose -f compose.build.yml up --build -d
```

## How the container runs

- Distroless Python image running as a non-root user (UID 65532), with no shell.
- Read-only filesystem with a temporary `/tmp`, all Linux capabilities dropped and
  `no-new-privileges` (set in both compose files).
- A health check on `/health`; `docker compose ps` shows its status.
