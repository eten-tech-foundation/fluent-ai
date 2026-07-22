# syntax=docker/dockerfile:1

# Base image: python:3.14-alpine3.24 pinned by digest for reproducible, auditable
# builds. Bump the digest intentionally after CVE review; do not float to `latest`.
FROM python:3.14-alpine3.24@sha256:26730869004e2b9c4b9ad09cab8625e81d256d1ce97e72df5520e806b1709f92 AS base

# OCI labels for traceability in registries and runtime inspection.
LABEL org.opencontainers.image.title="fluent-ai" \
      org.opencontainers.image.source="https://github.com/eten-tech-foundation/fluent-ai" \
      org.opencontainers.image.description="FastAPI backend for AI services in the Fluent ecosystem"

# Prevent Python from writing bytecode, enable unbuffered output, and keep uv's
# cache out of the image (we mount it as a build cache below).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/tmp/uv-cache \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONPATH="/app/src" \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# ---------------------------------------------------------------------------
# builder: resolves and installs the venv. This stage (and everything in it —
# uv, the compiler toolchain, the uv cache) is discarded; only /app/.venv and
# the app source are copied into the runtime stage below.
# ---------------------------------------------------------------------------
FROM base AS builder

# Build toolchain for any dependency that resolves to a musl-incompatible
# sdist (no prebuilt musllinux wheel for this Python/arch combination).
# Nothing in the current lockfile needs this (verified via `docker build
# --no-cache`), but isolating it to the builder stage means a future
# dependency bump that *does* need to compile won't silently break the
# build, and it never bloats the runtime image either way.
RUN apk update && apk add --no-cache build-base && rm -rf /var/cache/apk/*

# Pin uv by digest, not just tag, matching the same reproducibility bar as the
# Python base image above. Bump the tag and digest together deliberately.
COPY --from=ghcr.io/astral-sh/uv:0.11.30@sha256:93b61e21202b1dab861092748e46bbd6e0e41dd84f59b9174efd2353186e1b47 /uv /uvx /bin/

# Copy dependency manifests first to maximise layer reuse across code changes.
COPY pyproject.toml uv.lock ./

# Install runtime dependencies (no project, no dev deps) using a cache mount so
# the uv cache never enters the final image.
RUN --mount=type=cache,target=/tmp/uv-cache \
    uv sync --frozen --no-install-project --no-dev

# Copy application source only. Tests, docs, and dev configs are excluded via
# .dockerignore. `scripts/` is included so CI/CD can run out-of-band bootstrap
# and migrations using this same image (guaranteeing version-matched migrations).
COPY src/ ./src/
COPY alembic.ini ./
COPY scripts/ ./scripts/

# Install the project itself (still no dev deps).
RUN --mount=type=cache,target=/tmp/uv-cache \
    uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
# runtime: slim final image. No compiler, no uv, no uv cache, no build deps.
# ---------------------------------------------------------------------------
FROM base AS runtime

# Install dumb-init for proper PID 1 signal handling (graceful SIGTERM, zombie
# reaping) and curl for the HEALTHCHECK. Versions are pinned explicitly
# (instead of `apk upgrade`) so the same base image digest always produces the
# same package set — the same base digest built a week apart must resolve to
# identical bytes. Bump these deliberately alongside CVE review, same as the
# base image digest and uv version/digest above.
RUN apk update && \
    apk add --no-cache dumb-init=1.2.5-r4 curl=8.21.0-r0 && \
    rm -rf /var/cache/apk/*

# Create a non-root user (uid/gid 1001 to match compose/podman runtime) and a
# logs directory for file-based logging (LOG_OUTPUT=file|both). Alpine uses
# BusyBox addgroup/adduser rather than shadow-utils groupadd/useradd.
RUN addgroup -g 1001 -S python && \
    adduser -u 1001 -G python -S -s /bin/false -D -H python && \
    mkdir -p /app/logs && \
    chown -R python:python /app/logs

COPY --from=builder --chown=python:python /app/.venv ./.venv
COPY --from=builder --chown=python:python /app/src ./src
COPY --from=builder --chown=python:python /app/alembic.ini ./
COPY --from=builder --chown=python:python /app/scripts ./scripts

USER python

EXPOSE 8200

# Liveness/readiness probe. The /health endpoint is defined in app/main.py.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8200/health || exit 1

# dumb-init reaps zombies and forwards signals to uvicorn so SIGTERM drains
# in-flight requests instead of being dropped.
ENTRYPOINT ["dumb-init", "--"]

# Production server: invoke uvicorn directly from the venv (PATH already
# includes /app/.venv/bin). Avoid `uv run` here — it would re-sync the
# environment and pull in dev dependencies (ruff, mypy, etc.), and uv isn't
# even present in this stage.
#   --proxy-headers             trust X-Forwarded-* from the load balancer
#   --workers                   horizontal scaling is done by the orchestrator
#   --timeout-graceful-shutdown give in-flight requests time to finish on SIGTERM
#
# Database migrations and seeds are run out-of-band by CI/CD, NOT on container
# start. See AGENTS.md §Database Ownership and your deploy pipeline.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8200", \
     "--proxy-headers", \
     "--workers", "1", \
     "--timeout-graceful-shutdown", "30"]
