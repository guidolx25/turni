"""FastAPI entrypoint (spec §11)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
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

# Placeholder. Spec §11 requires structured logs and §8 requires solver runs
# logged with duration + objective values; those messages contain quotes and
# braces, so real JSON logging needs a formatter that escapes the payload
# (not an f-string-shaped format). Deferred to the §11 work.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

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
    scheduler = build_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Turni", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(root.router)
app.include_router(weeks.router)
app.include_router(constraints.router)
app.include_router(schedule.router)
app.include_router(notifications.router)
app.include_router(sacrifice.router)
app.include_router(swaps.router)
app.include_router(ics.router)
app.include_router(admin.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Health endpoint (spec §11)."""
    return {"status": "ok"}
