"""Admin lifecycle routes (spec §7 `-- admin --`).

Phase-3 scope is the manual solve trigger (§3.2 "Generate now"). Override, the
all-submissions view and the audit view arrive with their own increments and are
deliberately absent rather than stubbed. `require_admin` gates the tier; root
inherits it (§5).
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentAdmin, DbDep
from app.scheduling import ERROR_NOT_MONDAY, get_or_create_week
from app.schemas import SolveResultOut
from app.solve_service import run_solve

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/solve", response_model=SolveResultOut)
def admin_solve(week: dt.date, admin: CurrentAdmin, db: DbDep) -> SolveResultOut:
    """§3.2: run the solver for `week` now, closing its submission window.

    Idempotent — re-invoking regenerates the schedule. A feasible solve persists
    the assignments and returns the objective breakdown; an INFEASIBLE one persists
    nothing and returns the blocking constraints for the §2.3 sacrifice flow.
    """
    try:
        week_row = get_or_create_week(db, week)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERROR_NOT_MONDAY
        ) from exc
    return SolveResultOut.from_result(run_solve(db, week_row))
