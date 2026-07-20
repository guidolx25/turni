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
from app.enums import SacrificeStatus, WeekStatus
from app.models import SacrificeProposal, Week
from app.publish_service import ERROR_ALREADY_LOCKED, publish_week
from app.sacrifice_service import open_sacrifice
from app.scheduling import ERROR_NOT_MONDAY, get_or_create_week
from app.schemas import SolveResultOut, WeekOut
from app.solve_service import run_solve
from app.solver import SolverStatus

router = APIRouter(prefix="/admin", tags=["admin"])

# §9 keeps user-visible strings in the dictionaries; details are machine codes.
ERROR_WEEK_NOT_FOUND = "week_not_found"
# §2.3: a pending sacrifice conversation must be resolved before another solve —
# re-solving frozen constraints would only re-open a duplicate proposal.
ERROR_SACRIFICE_PENDING = "sacrifice_pending"


@router.post("/solve", response_model=SolveResultOut)
def admin_solve(week: dt.date, admin: CurrentAdmin, db: DbDep) -> SolveResultOut:
    """§3.2: run the solver for `week` now, closing its submission window.

    Idempotent regenerate — but only while the week is unpublished and not parked
    on an open conflict (§3.3 solve→review phase). Preconditions on the resolved
    week row (get_or_create_week may mint a fresh OPEN week, which proceeds):

    - LOCKED (published) → 409 `week_already_locked`. Post-lock changes happen only
      via swaps (§4) or admin override (§5/Phase 6), never a re-solve that would
      silently clobber the published rows (§3.4/§3.3).
    - a PENDING §2.3 sacrifice proposal for the week → 409 `sacrifice_pending`. The
      constraints are frozen, so a re-solve is deterministically INFEASIBLE again
      and would open a duplicate proposal (and duplicate worker notice); the offer
      must be accepted/declined first (§2.3).
    - OPEN, or SOLVED with no pending proposal → proceed and (re)generate.

    A feasible solve persists the assignments and returns the objective breakdown;
    an INFEASIBLE one persists nothing and opens the §2.3 sacrifice flow.
    """
    try:
        week_row = get_or_create_week(db, week)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERROR_NOT_MONDAY
        ) from exc
    if week_row.status is WeekStatus.LOCKED:
        # §3.4: a published week is immutable to solves — swaps/override only.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_ALREADY_LOCKED)
    pending = db.scalar(
        select(SacrificeProposal.id)
        .where(
            SacrificeProposal.week_id == week_row.id,
            SacrificeProposal.status == SacrificeStatus.PENDING,
        )
        .limit(1)
    )
    if pending is not None:
        # §2.3: resolve the open proposal before re-solving; never duplicate it.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_SACRIFICE_PENDING)
    result = run_solve(db, week_row, actor=admin)
    if result.status is SolverStatus.INFEASIBLE:
        # §2.3: open the sacrifice flow so an infeasible manual solve is never a
        # dead end — it proposes a free-day move or escalates to the admin.
        open_sacrifice(db, week_row, result)
    return SolveResultOut.from_result(result)


@router.post("/publish", response_model=WeekOut)
def admin_publish(week: dt.date, admin: CurrentAdmin, db: DbDep) -> WeekOut:
    """§3.3: publish a `solved` week — lock it (SOLVED→LOCKED), seed next week's
    solver_state, fan out the schedule_published notifications, audit.

    Distinct from solve (§3.2): a week must already be feasibly `solved`.
    `POST /admin/publish` is listed on the §7 API surface (spec v1.3) — §3.3 makes
    publish a required step an INFEASIBLE solve cannot reach — see
    `app.publish_service`. 409 if not solved (or parked in `solved` with no feasible
    rows) or already locked; 404 if the week does not exist.
    """
    week_row = db.scalar(select(Week).where(Week.monday_date == week))
    if week_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_WEEK_NOT_FOUND)
    return WeekOut.from_week(publish_week(db, week_row, admin))
