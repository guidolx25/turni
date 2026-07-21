# Single container (spec §11): FastAPI + APScheduler + the built frontend.
# §9 makes the frontend static assets served by FastAPI, so there is one
# deployable and one origin — which is also why the app needs no CORS config.

# --- stage 1: build the frontend -------------------------------------------
FROM node:24-slim AS frontend
WORKDIR /build
# Copy manifests first so `npm ci` is cached until dependencies actually change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# `npm run build` runs `tsc -b` first, so a type error fails the image build
# rather than shipping a broken bundle.
RUN npm run build

# --- stage 2: runtime -------------------------------------------------------
FROM python:3.12-slim AS runtime

# uv is the project's package manager; copy the binary rather than pip-installing.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # §11: Europe/Rome for ALL scheduling logic. The container's own clock stays
    # UTC (the DB stores UTC); this is what the app converts at its edges.
    TZ=Europe/Rome

# Dependencies as their own layer, from the lockfile, before the source.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY backend/ ./
# The SPA build lands where app.main mounts it.
COPY --from=frontend /build/dist ./static

# §11: SQLite lives on a persistent volume, and the nightly backup writes beside
# it. Created here so a first boot without a mounted volume still starts.
RUN mkdir -p /data /data/backups
ENV DATABASE_URL="sqlite:////data/turni.db" \
    BACKUP_DIR="/data/backups" \
    STATIC_DIR="/app/static"

EXPOSE 8000

# Migrations run at boot, not at build: the volume is only attached at runtime,
# and a container that starts against an un-migrated database would answer
# requests with a schema that does not exist.
#
# --proxy-headers + --forwarded-allow-ips closes the Phase 1 carry-forward: the
# per-IP login rate limit reads request.client.host, which behind a proxy is the
# PROXY for every request, collapsing the limit into one global bucket. The
# allow-list must name the proxy's address only — a wildcard would let any
# client forge X-Forwarded-For and restore the bypass the limit exists to
# prevent. FORWARDED_ALLOW_IPS is therefore required at deploy time and has no
# default: unset means uvicorn trusts nobody, which fails safe (the limit stays
# global) rather than open (spoofable).
CMD ["sh", "-c", "uv run alembic upgrade head && exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]
