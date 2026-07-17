"""FastAPI entrypoint (spec §11)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import (
    admin,
    auth,
    constraints,
    notifications,
    root,
    sacrifice,
    schedule,
    weeks,
)
from app.scheduler import build_scheduler

# Placeholder. Spec §11 requires structured logs and §8 requires solver runs
# logged with duration + objective values; those messages contain quotes and
# braces, so real JSON logging needs a formatter that escapes the payload
# (not an f-string-shaped format). Deferred to the §11 work.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Run the §3 window-close cron for the app's lifetime.

    Started here, not at import, so importing the app (and the test suite) never
    spins up a background thread — only a real server run does.
    """
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
app.include_router(admin.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Health endpoint (spec §11)."""
    return {"status": "ok"}
