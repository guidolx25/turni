"""Publish + lock a solved week (spec §3.3) — the step that makes it real.

Publishing is the transition after a feasible solve (§3.2): the schedule "becomes
visible to all, slots lock, notification fan-out" (§3.3). It also discharges the
Phase 2 carry-forward — writing each worker's `solver_state` from the fixed H5
weekend template so next week's solve sees the Sunday→Monday boundary (§2.2/§8).

Everything here commits in one transaction: lock + solver_state + fan-out + audit
land together, or not at all. The cron (Increment D) and the manual admin trigger
both call `publish_week`, so the lifecycle has exactly one publish path.

Publishing is the SOLVED→LOCKED transition (§3.3): only a `solved` week with
feasible solver rows can publish. `POST /admin/publish` (§7) is the manual trigger
for the step; §3.3 makes publish distinct from solve (an INFEASIBLE solve parks in
`solved` with no solver rows and can never publish).
"""

from __future__ import annotations

import datetime as dt

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.db import utcnow
from app.enums import AssignmentSource, Day, WeekStatus
from app.models import Assignment, SolverState, User, Week
from app.notifications import EVENT_SCHEDULE_PUBLISHED, notify
from app.solver import WeekendAssignment, compute_next_solver_state

# Machine codes (§9 keeps user-visible strings in the dictionaries).
ERROR_NOT_SOLVED = "week_not_solved"
ERROR_ALREADY_LOCKED = "week_already_locked"

_WEEKEND_DAYS = (Day.SAT, Day.SUN)
# Calendar offset of each day from the week's Monday (§6 weeks.monday_date).
_DAY_OFFSET: dict[Day, int] = {day: index for index, day in enumerate(Day)}


def publish_week(db: DbSession, week: Week, actor: User | None) -> Week:
    """§3.3: lock a `solved` week — seed next week's `solver_state`, fan out, audit.

    Preconditions (SOLVED→LOCKED): the week is `solved` and a feasible solve has
    left solver assignments. An already-`locked` week raises 409 ALREADY_LOCKED; a
    week that is not `solved`, or one parked in `solved` by an INFEASIBLE run,
    raises 409 NOT_SOLVED — an INFEASIBLE run clears the generated rows
    (`app.solve_service`), so "no solver rows" is a truthful unresolved signal.

    That signal is a backstop, not the conflict check: §3.3's "never published with
    an unresolved conflict" is enforced explicitly by the caller
    (`POST /admin/publish` rejects a PENDING §2.3 proposal), because a pending
    proposal can coexist with feasible rows from an earlier solve.

    `actor` is the human who published, or None for the cron.
    """
    if week.status is WeekStatus.LOCKED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_ALREADY_LOCKED)
    if week.status is not WeekStatus.SOLVED or not _has_solver_rows(db, week):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_NOT_SOLVED)

    week.status = WeekStatus.LOCKED
    week.locked_at = utcnow()

    write_solver_state(db, week)
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


def write_solver_state(db: DbSession, week: Week) -> None:
    """Derive each worker's Sunday→Monday boundary from the week's PERSISTED
    weekend rows and upsert it into `solver_state` (§2.2, §8).

    Read from the rows, not from `emit_weekend_template`: §2.2 states the
    invariant as a fact about reality — "each worker's last worked slot is
    persisted in `solver_state`" — and after publish that reality can still
    move. §2.1 H5 lets a post-lock bagnino↔bagnino swap trade Sunday AM for
    Sunday PM, and §5 lets an admin override a locked slot. Deriving from the
    ideal template would leave the stored boundary describing a Sunday that no
    longer happened, and §2.2 names precisely these two workers as the ones
    Monday's alternation is seeded from — so the error would land on the term
    it most affects.

    Idempotent, so any caller that changes weekend rows can simply re-run it.

    The write set is AUTHORITATIVE, not additive: a worker with no Sunday row in
    this week must end with no `solver_state` row at all, exactly as the jolly
    does (§2.2 — absent means no boundary term). Upserting alone would be a bug,
    because a weekend swap can move a worker OFF Sunday entirely: an H5-legal
    Sat↔Sun bagnino trade leaves one bagnino holding both Sunday slots and the
    other holding both Saturday slots, and the latter's stale row would keep
    seeding next Monday from a Sunday they did not work.

    Both the write and the clear are guarded on `last_worked_date`, which is why
    §6 dates the boundary at all: a swap on week N stays acceptable after week
    N+1 has published, and must not overwrite the newer week's boundary with its
    own older Sunday.

    The full-weekend workers get a NULL `last_worked_slot` (the FULL_DAY boundary
    the single am/pm column cannot hold)."""
    sunday = week.monday_date + dt.timedelta(days=_DAY_OFFSET[Day.SUN])
    weekend = tuple(
        WeekendAssignment(
            date=week.monday_date + dt.timedelta(days=_DAY_OFFSET[row.day]),
            slot=row.slot,
            role=row.role,
            worker_id=row.user_id,
        )
        for row in db.scalars(
            select(Assignment).where(
                Assignment.week_id == week.id, Assignment.day.in_(_WEEKEND_DAYS)
            )
        ).all()
    )
    worked_sunday: set[int] = set()
    for cont in compute_next_solver_state(weekend):
        worked_sunday.add(cont.worker_id)
        st = db.get(SolverState, cont.worker_id)
        if st is None:
            st = SolverState(user_id=cont.worker_id)
            db.add(st)
        elif _is_newer(st.last_worked_date, cont.last_worked_date):
            continue  # a later week already set this boundary; leave it alone
        st.last_worked_slot = cont.last_worked_slot
        st.last_worked_date = cont.last_worked_date

    # Anyone this week's Sunday does NOT include has no boundary to carry.
    #
    # Deliberately global, not scoped to this week's roster: `solver_state` is
    # keyed by user alone (§6) and holds ONE boundary per person — the most
    # recent one — so "who is absent from Sunday" can only be asked of the whole
    # table. The date guard is what makes that safe: a row belonging to a LATER
    # published week is newer than this Sunday and survives untouched, so weeks
    # published or swapped out of order cannot delete each other's boundaries.
    #
    # Deleting (rather than blanking) is the correct reading of §2.2: alternation
    # is calendar-adjacent, and Sunday is Monday's only neighbour. A worker who
    # did not work Sunday has no adjacent prior day, so they must contribute no
    # boundary term at all — which `_load_prior_state` expresses as an absent
    # row, exactly as it does for the jolly.
    for st in db.scalars(
        select(SolverState).where(SolverState.user_id.notin_(worked_sunday))
    ).all():
        if not _is_newer(st.last_worked_date, sunday):
            db.delete(st)


def _is_newer(stored: dt.date | None, candidate: dt.date) -> bool:
    """Is the STORED boundary from a later Sunday than `candidate`?

    An undated row cannot be ordered, so it never wins: it is treated as stale
    and yields to a dated one. Every row this module writes carries a date."""
    return stored is not None and stored > candidate


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
