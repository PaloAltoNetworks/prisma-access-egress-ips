# 0001: Distroless Python 3.13 runtime image

**Status:** accepted

## Context

The image had been built on the floating `python:3-alpine` tag: Python 3.14 at the time, running as
root. The standard offers two runtimes: distroless if `requires-python` can drop to 3.13, or a
digest-pinned, hardened `python:3.14-alpine`. Nothing in the code needs 3.14.

## Decision

- Runtime: `gcr.io/distroless/python3-debian13:nonroot`, pinned by digest, running as UID 65532.
  It has no shell or package manager, so a compromised process has very little to work with.
- `requires-python = ">=3.13"`, `.python-version` is `3.13`, and CI tests on 3.13.
- Builder: `debian:13-slim` with Debian's `python3.13` package, plus the pinned `uv` image. `uv sync
  --locked` creates `/app/.venv` against `/usr/bin/python3.13`, which is the same interpreter path
  and Debian build that distroless ships. The venv is copied over as is: no `PYTHONPATH`, and the
  project's package metadata (used for the version) comes with it.
- The `HEALTHCHECK` uses exec form and the venv's Python, because distroless has no `wget` or `curl`.

## Consequences

- No shell for debugging inside the container. Use `docker exec <id> /app/.venv/bin/python -c ...`
  or a temporary build of the builder stage.
- The Python minor follows Debian 13 (3.13). Moving to a newer Python means waiting for a newer
  distroless base or revisiting this decision.
- The builder's `apt-get install python3.13` resolves from the Debian 13 archive at build time.
  Nothing from apt reaches the runtime image except bytecode compiled with the same minor version.
- Dependabot bumps the uv, builder and runtime images together in one grouped PR.
