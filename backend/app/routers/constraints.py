"""Constraint CRUD routes (spec §7 `/constraints`, lifecycle §3.1).

Thin permission + shape layer over `app.constraints`: the upsert/exclusion rule
and the open-window guard live in `app.constraints` / `app.scheduling`, so these
handlers only pick the §5 tier (every caller edits their *own* rows, §5 row 1),
resolve the week, and translate service outcomes into HTTP.

Every write goes through `resolve_submittable_week`, so "editable only while the
week is open" (§3.1) is enforced in one place and cannot be forgotten per route.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.constraints import delete_own_constraint, list_own_constraints, upsert_constraint
from app.deps import CurrentWorker, DbDep
from app.models import Week
from app.scheduling import ERROR_WEEK_CLOSED, is_submittable, resolve_submittable_week
from app.schemas import ConstraintIn, ConstraintOut

router = APIRouter(tags=["constraints"])

# §9 keeps user-visible strings in the dictionaries; details are machine codes.
ERROR_CONSTRAINT_NOT_FOUND = "constraint_not_found"


@router.get("/constraints", response_model=list[ConstraintOut])
def get_constraints(week: dt.date, worker: CurrentWorker, db: DbDep) -> list[ConstraintOut]:
    """§7: the caller's own constraints for the week named by its Monday date
    (`?week=YYYY-MM-DD`; FastAPI 422s a malformed date).

    An unknown or not-yet-materialised week is simply empty — a worker who has
    submitted nothing yet is not an error. Never returns another user's rows.
    """
    week_row = db.scalar(select(Week).where(Week.monday_date == week))
    if week_row is None:
        return []
    return [ConstraintOut.from_model(c) for c in list_own_constraints(db, worker, week_row)]


@router.post("/constraints", response_model=ConstraintOut, status_code=status.HTTP_201_CREATED)
def post_constraint(body: ConstraintIn, worker: CurrentWorker, db: DbDep) -> ConstraintOut:
    """§3.1 upsert of one of the caller's own constraints. Rejects a closed window
    (409) before any row is written; applies the full_day ↔ am/pm exclusion."""
    week_row = resolve_submittable_week(db, body.week)
    row = upsert_constraint(db, worker, week_row, body.day, body.slot, body.kind, body.note)
    return ConstraintOut.from_model(row)


@router.delete("/constraints/{constraint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_constraint(constraint_id: int, worker: CurrentWorker, db: DbDep) -> None:
    """§7/§3.1: withdraw one of the caller's own constraints while its week is
    still open. 404 if it is not the caller's (no cross-user existence leak),
    409 if the week has since closed."""
    row = delete_own_constraint(db, worker, constraint_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_CONSTRAINT_NOT_FOUND
        )
    if not is_submittable(row.week):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_WEEK_CLOSED)
    db.delete(row)
    db.commit()
