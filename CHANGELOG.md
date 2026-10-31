# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **FedRAMP High** environment (`fedramp_high`, `api.highprod.prismasasegov.com`).
- The environment list groups environments under **Commercial** and **FedRAMP**. The page and
  server messages show the FedRAMP environments as "FedRAMP Moderate" and "FedRAMP High".
- A `:dev` image tag for pre-release builds that maintainers publish for testing. Builds
  published this way also get a `:sha-<commit>` tag. Not for production use.

### Changed

- FedRAMP environments are no longer searched when a key is rejected, and keys never cross
  between commercial and FedRAMP. Previously, a FedRAMP key used with a commercial environment
  selected was switched to `fedramp` automatically; it's now rejected, with a message to select
  the FedRAMP environment. A key rejected by a FedRAMP environment is reported as is, without
  trying other environments.

## [1.0.0] - 2026-10-30

First stable release. The web page and the compose files are the supported interface: a
breaking change to either now needs a new major version. The `/api/...` endpoints remain
internal to the web page.

### Added

- The page footer shows the running version, `/health` reports it
  (`{"status": "ok", "version": "..."}`), and the app logs it at startup.
- A `:1` image tag that follows the newest 1.x release, and documentation for running behind
  an explicit proxy (`HTTPS_PROXY`, `NO_PROXY`). Only the newest release is rebuilt weekly,
  so `:0.1` no longer receives base-image updates: move to `:1` or `:latest`.
- The Quick Start downloads `compose.yml` from the latest release, where it's attached,
  instead of from the `main` branch, which can carry unreleased changes.
- When the certificate dialog offers to trust a CA, it shows that CA's SHA-256 fingerprint,
  so you can compare it with the one your IT team published.

### Changed

- The certificate dialog's chain details are read through the configured proxy
  (`HTTPS_PROXY`), so they describe the path that was rejected.

### Fixed

- Batch mode fails with an error naming the node types it couldn't fetch, instead of showing
  them as empty. A missing type also left its IPs in lists they should be subtracted from,
  such as load-balancer IPs in `swg`.
- Rate limits and temporary server errors (429, 502, 503, 504) from the Prisma Access API are
  retried once before a query fails.
- When searching for the environment that accepts an API key, only a successful reply counts
  as a match. A server error from another environment no longer wins the search, and if some
  environments couldn't be checked, the error names them instead of saying the key was
  rejected everywhere.
- Timeouts report "Timed out reaching ..." instead of an empty message, and an unexpected
  response from the Prisma Access API (not JSON, or in the wrong shape) is reported as an
  error instead of a server crash or a shorter IP list. Upstream error bodies in messages
  are truncated.
- The "Environment auto-corrected to ..." notice is shown; it used to disappear immediately.
  The loading message is shown while a query runs.

### Security

- Approving a certificate after a verification failure trusts only that certificate, instead
  of turning verification off for every host. For an untrusted issuer, when the chain
  includes a CA above the server's certificate, that top certificate becomes an extra
  trusted CA, and hostnames and expiry are still checked. Otherwise only that exact
  certificate is accepted, and only for that host.
  Approvals are listed under the Query button and can be removed. `skip_tls_verify` is
  removed from the internal API.
- Requests are validated strictly: unknown fields are rejected, the API key and service
  account credentials have maximum lengths, the TSG ID must be numeric, and the bearer
  token for the locations endpoint must be a well-formed token of at most 8192
  characters. Invalid requests are rejected and never forwarded to Prisma Access.
- Validation errors no longer echo the rejected values, so an API key or secret can't
  end up in proxy or browser logs.
- The page sends a Content Security Policy that allows only its own scripts, styles and
  images (the page no longer uses inline handlers or styles), plus `X-Content-Type-Options`,
  `Referrer-Policy` and `frame-ancestors 'none'`. The page and its assets revalidate on
  every load, so an upgraded container never runs a cached script, and API responses are
  never cached.
- CSV exports neutralise values that a spreadsheet would run as formulas (starting with
  `=`, `+`, `-`, `@`, a space, tab or line break) by prefixing an apostrophe, which some
  spreadsheets display, and quote values with line breaks. Line breaks in zone and site
  names no longer split comment lines in TXT exports.
- Unexpected server errors carry the same security and cache headers as other responses.

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

[Unreleased]: https://github.com/PaloAltoNetworks/prisma-access-egress-ips/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/PaloAltoNetworks/prisma-access-egress-ips/compare/v0.1.1...v1.0.0
[0.1.1]: https://github.com/PaloAltoNetworks/prisma-access-egress-ips/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/PaloAltoNetworks/prisma-access-egress-ips/releases/tag/v0.1.0
