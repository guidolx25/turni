"""FastAPI entrypoint (spec §11)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import API_PREFIX, settings
from app.db import SessionLocal, utcnow
from app.deps import DbDep
from app.logging_config import configure_logging
from app.routers import (
    admin,
    auth,
    constraints,
    ics,
    notifications,
    root,
    sacrifice,
    schedule,
    swaps,
    weeks,
)
from app.scheduler import build_scheduler
from app.scheduling import ensure_horizon
from app.spa import mount_spa

# §11 structured logs. Configured at import, which is after uvicorn has installed
# its own handlers — see `app.logging_config`, which takes those over so request
# logs join the same JSON stream.
configure_logging(settings.log_level, json_format=settings.log_json)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Run the §3 window-close cron for the app's lifetime.

    Started here, not at import, so importing the app (and the test suite) never
    spins up a background thread — only a real server run does.
    """
    if settings.require_admin_approval:
        # §4 builds the pending_admin state; §13 defers the approval surface, so
        # nothing can move a swap out of it and the 48 h sweep only touches
        # `pending`. Enabling this strands every accepted swap. Loud, not fatal:
        # refusing to boot would be a worse failure for an operator who set it
        # by accident, and the swaps still exist to be released once the Phase 6
        # approval endpoint lands.
        logger.error(
            "REQUIRE_ADMIN_APPROVAL is ON, but the approval endpoint is deferred (spec §13): "
            "accepted swaps will park in `pending_admin` with no way out. Unset it unless you "
            "are deliberately freezing swaps."
        )
    # §3 rolling horizon. At startup as well as nightly, so a deployment that has
    # run out of open weeks recovers on its next restart rather than waiting for
    # 03:30 — and so the very first boot of a fresh install has somewhere to
    # submit before anyone has submitted anything.
    #
    # Failure here must not stop the app from booting: no open week is a bad day,
    # an API that will not start is a worse one, and /healthz stays honest either
    # way. The nightly run is the second chance.
    try:
        with SessionLocal() as db:
            created = ensure_horizon(db, utcnow())
            db.commit()
        logger.info("submission horizon ensured: %d week(s)", len(created))
    except SQLAlchemyError:
        logger.exception("could not ensure the submission horizon; the nightly job will retry")

    scheduler = build_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


health_router = APIRouter(tags=["health"])


def create_app(static_dir: Path | None = None) -> FastAPI:
    """Build the application.

    A factory rather than a module-level assembly so the SPA wiring can be
    exercised against a real build directory without a test mutating the
    process-wide `app` — `mount_spa` registers a catch-all, which on a shared
    instance would leak into every other suite's 404s.

    `static_dir` defaults to the configured one; §9's single-origin frontend is
    mounted last, after every router, because the fallback matches everything.
    """
    app = FastAPI(title="Turni", version="0.1.0", lifespan=lifespan)

    # §7 (v1.11): the whole API lives under /api. The prefix is applied here,
    # once, rather than in each router — the routers keep their spec-shaped paths
    # (/me, /swaps/{id}/accept) and the namespace is a mounting decision.
    #
    # It exists to separate the API from the §9 client routes. They previously
    # shared a namespace, so /swaps was both a react-router view and a real GET
    # endpoint, and the server had to guess which was meant from the `Accept`
    # header. A prefix makes the two sets disjoint by construction.
    api = APIRouter(prefix=API_PREFIX)
    api.include_router(auth.router)
    api.include_router(root.router)
    api.include_router(weeks.router)
    api.include_router(constraints.router)
    api.include_router(schedule.router)
    api.include_router(notifications.router)
    api.include_router(sacrifice.router)
    api.include_router(swaps.router)
    api.include_router(ics.router)
    api.include_router(admin.router)
    app.include_router(api)

    # §11: deliberately NOT under /api. This is infrastructure — the host's
    # health probe points at it, and that probe should not have to know the
    # application's URL layout. It is also the one endpoint that must keep
    # answering while the API is the thing that is broken.
    app.include_router(health_router)

    resolved_static = settings.static_dir if static_dir is None else static_dir
    if resolved_static is not None:
        mount_spa(app, resolved_static)

    return app


@health_router.get("/healthz")
def healthz(db: DbDep) -> dict[str, str]:
    """Health endpoint (spec §11).

    Answers a question the host's probe can act on: not merely "is the process
    listening" (the socket accepting already proves that) but "can this process
    reach its database". §11 puts SQLite on a persistent volume, and the failure
    this endpoint exists to catch is the volume not being mounted — a container
    that serves 200s while every real request 500s is precisely what a constant
    `{"status": "ok"}` would hide.

    Deliberately unauthenticated and deliberately shape-stable: a probe must not
    need a session, and the body stays `{"status": "ok"}` so nothing downstream
    parses a schema. An unreachable database is 503, which is what makes the
    check mean anything.
    """
    try:
        db.execute(select(1))
    except SQLAlchemyError:
        logger.exception("health check FAILED: database unreachable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database_unavailable"
        ) from None
    return {"status": "ok"}


# The ASGI target uvicorn is pointed at (`app.main:app`).
app = create_app()
