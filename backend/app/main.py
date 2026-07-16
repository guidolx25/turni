"""FastAPI entrypoint (spec §11)."""

import logging

from fastapi import FastAPI

from app.routers import auth, constraints, root, weeks

# Placeholder. Spec §11 requires structured logs and §8 requires solver runs
# logged with duration + objective values; those messages contain quotes and
# braces, so real JSON logging needs a formatter that escapes the payload
# (not an f-string-shaped format). Deferred to the §11 work.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="Turni", version="0.1.0")

app.include_router(auth.router)
app.include_router(root.router)
app.include_router(weeks.router)
app.include_router(constraints.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Health endpoint (spec §11)."""
    return {"status": "ok"}
