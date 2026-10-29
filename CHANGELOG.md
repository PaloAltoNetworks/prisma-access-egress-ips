# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Versioned releases. Images are published as `:X.Y.Z`, `:X.Y` and `:latest`.
- `/api/openapi.json` reports the version from `pyproject.toml`.
- Container `HEALTHCHECK` on `/health`.

### Changed

- Runtime image is now distroless Python 3.13 running as non-root, built from the
  committed `uv.lock`. Base images are pinned by digest.
- The user compose file runs the container read-only, with all capabilities dropped
  and `no-new-privileges`.
- `:latest` now tracks the newest release instead of every commit to `main`. Commits
  to `main` are published as `:main`.

[Unreleased]: https://github.com/PaloAltoNetworks/prisma-access-egress-ips/commits/main
