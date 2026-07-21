"""Admin lifecycle routes (spec §7 `-- admin --`).

The full §5 admin tier: solve and publish (§3.2/§3.3), override a locked slot
(§5, §3.4), view every worker's submissions, view the audit log. `require_admin`
gates all of them; root inherits the tier (§5) without `is_admin` being set.

These handlers stay thin on purpose — the override's rules live in
`app.override_service`, the lifecycle's in `app.solve_service` /
`app.publish_service` — so a route declares its authority and its shape, and the
domain rule has exactly one home.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.deps import CurrentAdmin, DbDep
from app.enums import SacrificeStatus, WeekStatus
from app.models import AuditLog, Constraint, SacrificeProposal, User, Week
from app.override_service import OverrideSpec, apply_override
from app.publish_service import ERROR_ALREADY_LOCKED, publish_week
from app.sacrifice_service import open_sacrifice
from app.scheduling import ERROR_NOT_MONDAY, get_or_create_week
from app.schemas import (
    AdminConstraintOut,
    AdminConstraintsOut,
    AuditEntryOut,
    AuditPageOut,
    OverrideIn,
    OverrideOut,
    ScheduleAssignmentOut,
    SolveResultOut,
    ViolationOut,
    WeekOut,
)
from app.solve_service import run_solve
from app.solver import SolverStatus

router = APIRouter(prefix="/admin", tags=["admin"])

# §9 keeps user-visible strings in the dictionaries; details are machine codes.
ERROR_WEEK_NOT_FOUND = "week_not_found"

# §7 `GET /admin/audit` paging. Capped so one request cannot ask the server to
# serialize the entire history of the installation into memory.
AUDIT_DEFAULT_LIMIT = 50
AUDIT_MAX_LIMIT = 200
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
    if _has_pending_sacrifice(db, week_row):
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

    §3.3 "never published with an unresolved conflict" is checked HERE and
    explicitly: a PENDING §2.3 proposal → 409 `sacrifice_pending`, the same guard
    `/admin/solve` applies. Relying on `publish_service`'s no-solver-rows test
    instead would be an indirect signal that a week solved feasibly *before* the
    conflict arose would pass.
    """
    week_row = db.scalar(select(Week).where(Week.monday_date == week))
    if week_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_WEEK_NOT_FOUND)
    if _has_pending_sacrifice(db, week_row):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_SACRIFICE_PENDING)
    return WeekOut.from_week(publish_week(db, week_row, admin))


@router.post("/override", response_model=OverrideOut)
def admin_override(body: OverrideIn, admin: CurrentAdmin, db: DbDep) -> OverrideOut:
    """§5/§3.4: change who holds a locked slot.

    One of the two post-lock instruments (§3.4); the other is the peer-approved
    swap (§4). Unlike a swap it is unilateral, and — deliberately — it may leave
    H2/H3/H4 standing violated: those bind the SOLVER (§2.1/§8), while §5 grants
    the admin authority over the locked *result* precisely for the situations the
    model cannot express. The full argument, and the three things that keep it
    from being silent (audit, §10 `admin_override` to both affected workers, and
    the violations echoed here), are in `app.override_service`.

    Errors: 404 `week_not_found`; 409 `week_not_locked` (§3.4 — an unpublished
    week is regenerated, not overridden), `override_no_change`,
    `override_ambiguous_slot` (an H5 weekend slot with two holders and no
    `assignment_id`); 422 `override_user_not_found`, `override_user_inactive`,
    `override_role_invalid` (§1/H1 — the one rule an override may not bend),
    `override_row_mismatch`.
    """
    outcome = apply_override(
        db,
        admin,
        OverrideSpec(
            week=body.week,
            day=body.day,
            slot=body.slot,
            role=body.role,
            user_id=body.user_id,
            assignment_id=body.assignment_id,
        ),
    )
    db.refresh(outcome.assignment)
    return OverrideOut(
        assignment=ScheduleAssignmentOut.from_model(outcome.assignment),
        previous_user_id=outcome.previous_user_id,
        new_user_id=outcome.new_user_id,
        created=outcome.created,
        violations=[
            ViolationOut(rule=v.rule, user_id=v.user_id, day=v.day, slot=v.slot)
            for v in outcome.violations
        ],
    )


@router.get("/constraints", response_model=AdminConstraintsOut)
def admin_constraints(week: dt.date, admin: CurrentAdmin, db: DbDep) -> AdminConstraintsOut:
    """§5/§7: every worker's submissions for one week, named by its Monday date.

    Root's own rows are included: §5 hides the root ROLE from user lists, worker
    pickers and role-based fan-outs — not the fact that Matteo is a working
    bagnino who submits constraints like everyone else. `is_root` is not
    serialized (it exists on no response model at all), so including his
    submissions discloses a worker, never an authority.

    404 if the week has never been materialised — a GET must not create a week
    row as a side effect of being asked about one.
    """
    week_row = db.scalar(select(Week).where(Week.monday_date == week))
    if week_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_WEEK_NOT_FOUND)
    rows = db.scalars(
        select(Constraint)
        .join(User, User.id == Constraint.user_id)
        .where(Constraint.week_id == week_row.id)
        .order_by(User.display_name, Constraint.day, Constraint.slot)
    ).all()
    return AdminConstraintsOut(
        week=week_row.monday_date,
        status=week_row.status,
        constraints=[AdminConstraintOut.from_model(c) for c in rows],
    )


@router.get("/audit", response_model=AuditPageOut)
def admin_audit(
    admin: CurrentAdmin,
    db: DbDep,
    limit: int = Query(default=AUDIT_DEFAULT_LIMIT, ge=1, le=AUDIT_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, max_length=64),
    entity: str | None = Query(default=None, max_length=64),
) -> AuditPageOut:
    """§5/§7: the audit log, newest first, paginated and optionally filtered.

    Ordered by `created_at` DESC then `id` DESC: several rows of one transaction
    share a timestamp (they are written together, §6), and only the id orders them
    stably — without it a page boundary could repeat or skip a row.

    A NULL `actor_id` is a system action (§6: cron solve, 48 h swap expiry,
    nightly backup — "there is deliberately no system user row"). The response
    says so with `system: true` rather than emitting a null name the panel would
    have to guess at.
    """
    filters = []
    if action is not None:
        filters.append(AuditLog.action == action)
    if entity is not None:
        filters.append(AuditLog.entity == entity)

    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    rows = db.scalars(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return AuditPageOut(
        total=int(total),
        limit=limit,
        offset=offset,
        entries=[AuditEntryOut.from_model(row) for row in rows],
    )


def _has_pending_sacrifice(db: DbSession, week: Week) -> bool:
    """§2.3: is this week parked on an unresolved sacrifice conversation? Shared by
    solve and publish so the two cannot drift on what "unresolved" means."""
    pending = db.scalar(
        select(SacrificeProposal.id)
        .where(
            SacrificeProposal.week_id == week.id,
            SacrificeProposal.status == SacrificeStatus.PENDING,
        )
        .limit(1)
    )
    return pending is not None
