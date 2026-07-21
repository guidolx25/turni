"""Serving the built frontend from the API process (spec §9, §11).

§9 makes this one deployable with one origin: FastAPI answers both the API and
the SPA, which is why the app needs no CORS configuration anywhere. The image
builds `frontend/` and drops the result in `STATIC_DIR`; this module is what
actually puts it on the wire.

Two things make it more than a `StaticFiles` mount:

* **History fallback.** The frontend routes client-side (react-router), so a
  deep link like `/admin` or a refresh on `/swaps` arrives at the server as a
  path with no file behind it. It must answer with the SPA shell and let the
  client router take over, or every reload outside `/` is a 404.
* **The API must keep answering JSON.** A blanket fallback would hand an HTML
  page to a mistyped or removed API path. Clients parse those responses; a 404
  that arrives as `<!doctype html>` surfaces as a JSON parse error rather than
  the 404 it is, which is a genuinely miserable thing to debug.

Since v1.11 the split is a prefix: everything under `/api` is the API, and
everything else is the client's. That is the whole rule. It replaces an earlier
scheme that inspected the `Accept` header to decide whether `GET /swaps` meant
the react-router view or the endpoint of the same name — necessary when the two
shared a namespace, and worth deleting the moment they stopped, because it made
correct routing depend on a header any proxy in the path is free to rewrite.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import API_PREFIX

logger = logging.getLogger(__name__)

# Paths FastAPI itself owns. They sit outside `API_PREFIX` and outside any
# router, so `api_segments` cannot discover them, and a fallback that swallowed
# them would replace the API docs with the SPA shell.
_FRAMEWORK_SEGMENTS = frozenset({"docs", "redoc", "openapi.json"})

# Where the built assets live inside STATIC_DIR. Vite emits hashed files here.
_ASSETS_DIRNAME = "assets"


def api_segments(app: FastAPI) -> frozenset[str]:
    """The first path segment of every route registered on `app`.

    Since v1.11 this is a **safety net, not the mechanism**: with the API behind
    `/api` the prefix check below already separates the two namespaces, and this
    set is essentially `{"api", "healthz", "docs", …}`. It is kept because it
    costs nothing and it fails in the safe direction — if a future router is ever
    mounted outside the prefix, its 404s keep the API's JSON shape instead of
    silently becoming HTML, which is the failure that is hard to notice.

    Derived from the app rather than hardcoded, for the same reason.
    """
    segments = set(_FRAMEWORK_SEGMENTS)
    for path in app.openapi()["paths"]:
        head = path.lstrip("/").split("/", 1)[0]
        if head:
            segments.add(head)
    return frozenset(segments)


def mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the built frontend from `static_dir` on `app`.

    Must be called *after* every router is registered: the fallback matches any
    path, so anything added afterwards would be shadowed by it. It also reads the
    registered routes to build the safety net above.
    """
    index = static_dir / "index.html"
    if not index.is_file():
        # Loud, not fatal. A missing build is a broken image, but the API half
        # still works and refusing to boot would take down a running deployment
        # over a frontend problem. The health check stays honest either way.
        logger.error(
            "STATIC_DIR=%s has no index.html: the API will serve, the frontend will 404",
            static_dir,
        )
        return

    assets = static_dir / _ASSETS_DIRNAME
    if assets.is_dir():
        # Mounted, not routed through the fallback, so hashed bundles get
        # StaticFiles' conditional-request handling instead of a bare read.
        app.mount(
            f"/{_ASSETS_DIRNAME}",
            StaticFiles(directory=assets),
            name=_ASSETS_DIRNAME,
        )

    reserved = api_segments(app)
    api_head = API_PREFIX.strip("/")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        """Any non-API GET gets the SPA shell; the client router reads the URL."""
        stripped = full_path.lstrip("/")
        head, _, rest = stripped.partition("/")

        # The rule. Anything under /api that reached here matched no route, so it
        # is a mistyped or removed endpoint and must answer as the API does. The
        # bare /api is included: it is not a client route either.
        if head == api_head:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

        # The net (see `api_segments`). Only paths *under* a non-/api route's
        # segment are claimed, so a client route that happens to share a name
        # with one keeps working.
        if head in reserved and rest:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

        candidate = static_dir / full_path
        # A real file that is not under /assets (favicon.svg, robots.txt).
        # `resolve()` + `is_relative_to` blocks `../` traversal out of the build
        # directory; without it this handler would read arbitrary files.
        if full_path:
            resolved = candidate.resolve()
            if resolved.is_file() and resolved.is_relative_to(static_dir.resolve()):
                return FileResponse(resolved)

        return FileResponse(index)
