"""Publish + lock a solved week (spec §3.3) — the step that makes it real.

Publishing is the transition after a feasible solve (§3.2): the schedule "becomes
visible to all, slots lock, notification fan-out" (§3.3). It also discharges the
Phase 2 carry-forward — writing each worker's `solver_state` from the fixed H5
weekend template so next week's solve sees the Sunday→Monday boundary (§2.2/§8).

Everything here commits in one transaction: lock + solver_state + fan-out + audit
land together, or not at all. The cron (Increment D) and the manual admin trigger
both call `publish_week`, so the lifecycle has exactly one publish path.

Note on §7: the API surface lists no publish endpoint, but §3.3 makes publish a
required lifecycle step distinct from solve (an INFEASIBLE solve cannot publish).
`POST /admin/publish` is therefore added as the manual trigger, flagged for the
gate review.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.db import utcnow
from app.enums import AssignmentSource, WeekStatus
from app.models import Assignment, SolverState, User, Week
from app.notifications import EVENT_SCHEDULE_PUBLISHED, notify
from app.solve_service import build_roster
from app.solver import compute_next_solver_state, emit_weekend_template

# Machine codes (§9 keeps user-visible strings in the dictionaries).
ERROR_NOT_SOLVED = "week_not_solved"
ERROR_ALREADY_LOCKED = "week_already_locked"


def publish_week(db: DbSession, week: Week, actor: User | None) -> Week:
    """§3.3: lock `week`, seed next week's `solver_state`, fan out, audit.

    Preconditions: the week is not already locked, and a feasible solve has left
    solver assignments (a bare `solved_at` from an INFEASIBLE run is not enough).
    Raises 409 otherwise. `actor` is the human who published, or None for the cron.
    """
    if week.status is WeekStatus.LOCKED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_ALREADY_LOCKED)
    if week.solved_at is None or not _has_solver_rows(db, week):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_NOT_SOLVED)

    week.status = WeekStatus.LOCKED
    week.locked_at = utcnow()

    _write_solver_state(db, week)
    _fan_out_published(db, week)
    audit.record(
        db, actor, audit.ACTION_PUBLISH, "week", week.id, {"monday": week.monday_date.isoformat()}
    )
    db.commit()
    return week


def _has_solver_rows(db: DbSession, week: Week) -> bool:
    count = db.scalar(
        select(func.count())
        .select_from(Assignment)
        .where(Assignment.week_id == week.id, Assignment.source == AssignmentSource.SOLVER)
    )
    return bool(count)


def _write_solver_state(db: DbSession, week: Week) -> None:
    """Discharge the Phase 2 carry-forward: derive each worker's Sunday→Monday
    boundary from the fixed H5 template and upsert it into `solver_state` (§8).

    The full-weekend workers get a NULL `last_worked_slot` (the FULL_DAY boundary
    the single am/pm column cannot hold); the jolly, absent from the template's
    Sunday rows, gets no row at all — no boundary term next week (§2.2)."""
    weekend = emit_weekend_template(build_roster(db), week.monday_date)
    for cont in compute_next_solver_state(weekend):
        st = db.get(SolverState, cont.worker_id)
        if st is None:
            st = SolverState(user_id=cont.worker_id)
            db.add(st)
        st.last_worked_slot = cont.last_worked_slot
        st.last_worked_date = cont.last_worked_date


def _fan_out_published(db: DbSession, week: Week) -> None:
    """§3.3/§10: notify every active worker their schedule is published.

    Per-user, not role-based: each worker is told about their own week, so root
    (Matteo, a working bagnino) receives his own notification. §5 hides root from
    *role-based* fan-outs (e.g. "all admins"), not from a broadcast about the
    schedule they personally work.
    """
    recipients = db.scalars(select(User).where(User.active.is_(True))).all()
    for user in recipients:
        notify(db, user, EVENT_SCHEDULE_PUBLISHED, {"week": week.monday_date.isoformat()})
