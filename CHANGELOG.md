# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The page footer shows the running version, `/health` reports it
  (`{"status": "ok", "version": "..."}`), and the app logs it at startup.

### Changed

- The certificate dialog's chain details are read through the configured proxy
  (`HTTPS_PROXY`), so they describe the path that was rejected.

### Security

- Approving a certificate after a verification failure trusts only that certificate, instead
  of turning verification off for every host. For an untrusted issuer, the top certificate
  presented becomes an extra trusted CA, and hostnames and expiry are still checked. For
  any other failure, only that exact certificate is accepted, and only for that host.
  Approvals are listed under the Query button and can be removed. `skip_tls_verify` is
  removed from the internal API.
- Requests are validated strictly: unknown fields are rejected, the API key and service
  account credentials have maximum lengths, the TSG ID must be numeric, and the bearer
  token for the locations endpoint must be a well-formed token of at most 8192
  characters. Invalid requests are rejected and never forwarded to Prisma Access.
- Validation errors no longer echo the rejected values, so an API key or secret can't
  end up in proxy or browser logs.

## [0.1.1] - 2026-10-29

### Added

- Deployment and reference guides in `docs/`, and a security policy (`SECURITY.md`).

### Changed

- The compose files publish the port on `127.0.0.1` only, so the tool is reachable from the
  machine running it and not the rest of the network. See `docs/deployment.md` to share it.
- The README covers the default setup only, and links to the guides for everything else.

### Removed

- The interactive API documentation (`/api/docs`, `/api/redoc`, `/api/openapi.json`). The
  `/api/...` endpoints serve the web page only and aren't a supported interface; to automate
  lookups, use the Prisma Access egress IP API directly.

### Fixed

- Results tables and batch tabs build the page with text-only DOM operations, so data
  from the Prisma Access API can never be interpreted as HTML.

## [0.1.0] - 2026-10-29

### Added

- Versioned releases. Images are published as `:0.1.0`, `:0.1` and `:latest`.
- Custom CA support for networks that decrypt TLS: mount your organization's CA
  certificates at `/certs`. See [docs/custom-ca.md](docs/custom-ca.md).
- `/api/openapi.json` reports the version from `pyproject.toml`.
- Container `HEALTHCHECK` on `/health`.

### Changed

- Runtime image is now distroless Python 3.13 running as non-root, built from the
  committed `uv.lock`. Base images are pinned by digest.
- The user compose file runs the container read-only, with all capabilities dropped
  and `no-new-privileges`.
- `:latest` now tracks the newest release instead of every commit to `main`. Commits
  to `main` are published as `:main`.

### Fixed

- Password managers (1Password, LastPass, Bitwarden, Dashlane) no longer offer to
  save the API key as a login.

### Security

- TLS certificates are always verified. When verification fails, the app shows the
  certificate chain it was given and asks before skipping verification for the rest
  of the browser session, instead of retrying automatically.

[Unreleased]: https://github.com/PaloAltoNetworks/prisma-access-egress-ips/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/PaloAltoNetworks/prisma-access-egress-ips/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/PaloAltoNetworks/prisma-access-egress-ips/releases/tag/v0.1.0
