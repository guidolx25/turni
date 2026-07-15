"""A test-only app mounting one route per spec §5 tier.

The real API has no admin-tier route yet — §7's `/admin/*` surface arrives with
the constraints lifecycle — so `require_admin` currently guards nothing that a
request can reach. Mounting the dependency on a route of our own is the only way
to prove today that the middle row of the matrix behaves: that a worker is
refused, that root inherits it (§5), and that `is_admin` still does not open the
root tier.

The real routers are included so the probes are exercised behind the real login,
the real cookie and the real session store rather than a stub. Nothing here is
API surface: it is never mounted on `app.main.app`, whose OpenAPI document other
tests assert against.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.deps import CurrentAdmin, CurrentRoot, CurrentWorker
from app.routers import auth, root

probe_app = FastAPI(title="probe")

probe_app.include_router(auth.router)
probe_app.include_router(root.router)


@probe_app.get("/probe/worker")
def probe_worker(user: CurrentWorker) -> dict[str, str]:
    """§5 rows 1-2: any authenticated, active user."""
    return {"username": user.username}


@probe_app.get("/probe/admin")
def probe_admin(user: CurrentAdmin) -> dict[str, str]:
    """§5 rows 3-6: solve, override, all submissions, audit log."""
    return {"username": user.username}


@probe_app.get("/probe/root")
def probe_root(user: CurrentRoot) -> dict[str, str]:
    """§5 rows 7-8: user management, seeing the root account."""
    return {"username": user.username}
