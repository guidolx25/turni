"""Admin lifecycle routes (spec §7 `-- admin --`).

Phase-3 scope is the manual solve trigger (§3.2 "Generate now"). Override, the
all-submissions view and the audit view arrive with their own increments and are
deliberately absent rather than stubbed. `require_admin` gates the tier; root
inherits it (§5).
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CurrentAdmin, DbDep
from app.models import Week
from app.publish_service import publish_week
from app.scheduling import ERROR_NOT_MONDAY, get_or_create_week
from app.schemas import SolveResultOut, WeekOut
from app.solve_service import run_solve

router = APIRouter(prefix="/admin", tags=["admin"])

# §9 keeps user-visible strings in the dictionaries; details are machine codes.
ERROR_WEEK_NOT_FOUND = "week_not_found"


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


@router.post("/publish", response_model=WeekOut)
def admin_publish(week: dt.date, admin: CurrentAdmin, db: DbDep) -> WeekOut:
    """§3.3: publish a solved week — lock it, seed next week's solver_state, fan
    out the schedule_published notifications, audit.

    Distinct from solve (§3.2): a week must already be feasibly solved. §7 lists no
    publish endpoint, but §3.3 makes publish a required step an INFEASIBLE solve
    cannot reach — see `app.publish_service`. 409 if unsolved or already locked.
    """
    week_row = db.scalar(select(Week).where(Week.monday_date == week))
    if week_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_WEEK_NOT_FOUND)
    return WeekOut.from_week(publish_week(db, week_row, admin))
