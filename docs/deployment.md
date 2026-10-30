# Deployment

The [Quick Start](../README.md#quick-start) covers the default setup: the hosted image, newest
release, listening only on your machine. This page covers everything else.

## Image tags

Images are published to the GitHub Container Registry for `linux/amd64` and `linux/arm64`:
`ghcr.io/paloaltonetworks/prisma-access-egress-ips`.

| Tag | Tracks |
| --- | ------ |
| `:latest` | Newest release, including a new major version |
| `:1` | Newest `1.x` release: features and fixes, nothing that needs changes on your side |
| `:1.0` | Newest `1.0.x` patch release |
| `:1.0.0` | One exact release |
| `:main` | Unreleased `main` branch, for testing only |

A new major version (`2.0.0`) is only released for changes you have to act on, such as a
change to the compose file. `:latest` moves to it; `:1` doesn't.

Every week the newest release is rebuilt on fresh base images to pick up OS security patches. Its
tags keep the same version but get a new digest. Older releases are not rebuilt: once `2.0.0`
exists, `:1` stays on the last `1.x` build and gets no more patches. See the
[Changelog](../CHANGELOG.md) for what each release changed.

### Pinning a release

For anything beyond trying the tool, pin a release line in `compose.yml` so updates are
deliberate:

```yaml
services:
  app:
    image: ghcr.io/paloaltonetworks/prisma-access-egress-ips:1
```

`:1` gets every 1.x release, `:1.0` only patch releases, and `:1.0.0` never changes version.
`:1` and `:1.0` also get the weekly rebuild while they point at the newest release. Then
`docker compose pull && docker compose up -d` updates within that line. Read the
[Changelog](../CHANGELOG.md) before moving to a new major version.

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
| `api.sase.paloaltonetworks.com` | Prisma Access locations (not used by the web page yet) |
| `auth.apps.paloaltonetworks.com` | OAuth tokens for the locations API (not used by the web page yet) |

If your network decrypts TLS, see [Trusting a custom CA](./custom-ca.md).

### Using an outbound proxy

If the container has to reach the internet through an explicit proxy, set `HTTPS_PROXY` in
`compose.yml`. Hosts listed in `NO_PROXY` are reached directly:

```yaml
services:
  app:
    # ...
    environment:
      HTTPS_PROXY: http://proxy.example.com:8080
      NO_PROXY: localhost,127.0.0.1
```

Keep `localhost,127.0.0.1` in `NO_PROXY` so the container's health check isn't sent to the proxy.
All queries go through the proxy, and so does the connection that reads a certificate chain
for the certificate failure dialog, so the dialog shows what the proxied path presented. If the
proxy decrypts TLS, also mount its CA (see [Trusting a custom CA](./custom-ca.md)).

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
- A health check on `/health`; `docker compose ps` shows its status. `/health` also
  reports the running version, which the page footer shows.
