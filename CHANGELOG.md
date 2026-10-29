# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/PaloAltoNetworks/prisma-access-egress-ips/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/PaloAltoNetworks/prisma-access-egress-ips/releases/tag/v0.1.0
