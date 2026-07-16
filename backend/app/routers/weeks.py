"""Week lifecycle read routes (spec §7 `GET /weeks`).

Returns the persisted §6 `weeks` rows with their derived Sunday-17:00 deadlines
(§3.1) so the frontend can show which weeks are open and when each closes. Weeks
are materialised lazily by the first constraint submission (see
`app.scheduling.get_or_create_week`), so a brand-new install lists nothing until
someone submits — which is correct, not empty-by-bug.

Read-only and returns no user rows, so there is no root-visibility surface here
(§5); the schedule/assignment read that *does* name workers arrives with the
solver wiring.
"""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import CurrentWorker, DbDep
from app.models import Week
from app.schemas import WeekOut

router = APIRouter(tags=["weeks"])


@router.get("/weeks", response_model=list[WeekOut])
def list_weeks(worker: CurrentWorker, db: DbDep) -> list[WeekOut]:
    """§7: every week's status and submission deadline, newest first.

    Any authenticated worker may read the lifecycle calendar (§5 row 2 is
    unconditional); the response carries no other user's data.
    """
    weeks = db.scalars(select(Week).order_by(Week.monday_date.desc())).all()
    return [WeekOut.from_week(w) for w in weeks]
