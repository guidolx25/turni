"""FastAPI entrypoint (spec §11)."""

import logging

from fastapi import FastAPI

# Phase 0 stub. Spec §11 requires structured logs and §8 requires solver runs
# logged with duration + objective values; those messages contain quotes and
# braces, so real JSON logging needs a formatter that escapes the payload
# (not an f-string-shaped format). Deferred to the §11 work — see phase-gates.md.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="Turni", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Health endpoint (spec §11)."""
    return {"status": "ok"}
