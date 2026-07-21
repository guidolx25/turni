"""The DB ↔ solver adapter (spec §8): map §6 rows onto the pure `solve()` and back.

The solver (`app.solver`) is deliberately pure — no DB, no I/O. This module is the
one place §6 `users`/`constraints`/`solver_state` rows become a `SolverInput`, and
the returned `SlotAssignment`s (plus the fixed H5 weekend template) become §6
`assignments` rows. Keeping the mapping here means the solver never learns about
SQLAlchemy and the routes never learn about CP-SAT.

Roster note (§5): the solve roster is every ACTIVE user, *including* root (Matteo
is a working core bagnino). Root invisibility hides the root *role* from user
lists, pickers and role-based fan-out — not the duty roster. So this is one of the
few `select(User)` sites that deliberately does NOT go through `visible_users_stmt`.
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.db import utcnow
from app.enums import AssignmentSource, Day, SacrificeStatus, UserRole, WeekStatus
from app.models import Assignment, Constraint, SacrificeProposal, SolverState, User, Week
from app.solver import (
    PersonalConstraint,
    PriorSlot,
    SolverInput,
    SolverResult,
    SolverStatus,
    WorkerRef,
    emit_weekend_template,
    solve,
)
from app.solver.weights import DEFAULT_WEIGHTS

# Assignment rows this module owns and replaces on every (re)solve. Swap/override
# rows (§4/§5) are authored elsewhere and must survive a regenerate untouched.
_GENERATED_SOURCES = (AssignmentSource.SOLVER, AssignmentSource.WEEKEND_TEMPLATE)


def build_roster(db: DbSession) -> tuple[WorkerRef, ...]:
    """The duty roster the solver sees: every active user as a `WorkerRef`, by id.

    `is_core`/`is_jolly` key off role, never identity (§1): the jolly is the swing
    worker, everyone else is a core worker with an H3 free day. Root is included —
    it is a working member (see module docstring).
    """
    users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.id)).all()
    return tuple(
        WorkerRef(
            id=u.id,
            display_name=u.display_name,
            role=u.role,
            is_core=u.role is not UserRole.JOLLY,
            is_jolly=u.role is UserRole.JOLLY,
        )
        for u in users
    )


def accepted_sacrifice_grants(db: DbSession, week: Week) -> dict[int, Day]:
    """§2.1 H3 / §2.3 (v1.6): the week's grant of record — one granted free day
    per worker with an ACCEPTED `sacrifice_proposals` row.

    The single reader of that rule: every solve (`build_solver_input`) and every
    post-lock H3 re-check (§4 swap validation, `app.swap_service`) resolves the
    extended free-day domain through this helper, so "what days may this worker
    be free" cannot fork between the solver and the swap validator.
    """
    return {
        p.user_id: p.proposed_free_day
        for p in db.scalars(
            select(SacrificeProposal).where(
                SacrificeProposal.week_id == week.id,
                SacrificeProposal.status == SacrificeStatus.ACCEPTED,
            )
        ).all()
    }


def build_solver_input(
    db: DbSession,
    week: Week,
    roster: tuple[WorkerRef, ...],
    free_day_pins: Mapping[int, Day] | None = None,
    sacrifice_grants: Mapping[int, Day] | None = None,
) -> SolverInput:
    """Assemble the pure `SolverInput` for `week` from §6 rows.

    Sacrifice grants (§2.1 H3) reach the model from TWO sources, merged here:

    - **The grant of record (v1.6):** every ACCEPTED `sacrifice_proposals` row for
      this week. Reading them HERE — not at any single call site — is what makes
      the grant durable: every solve of the week (cron, manual, regenerate, the
      accept re-solve itself) carries it, so an accepted week can never relapse
      into INFEASIBLE because a call-scoped grant evaporated.
    - **The explicit `sacrifice_grants` argument:** the §2.3 probe, whose proposal
      does not exist yet. It merges on top (no legitimate key collision: probes
      target only workers with no answered proposal).

    `free_day_pins` and the explicit grants are EMPTY for a normal solve; on a
    week with no accepted proposal the H3 domains are then exactly the H3(b) role
    domains — {Mon, Tue} for the spiaggini, {Tue, Wed} for the bagnini (v1.12).
    """
    constraints = tuple(
        PersonalConstraint(worker_id=c.user_id, day=c.day, slot=c.slot, kind=c.kind)
        for c in db.scalars(select(Constraint).where(Constraint.week_id == week.id)).all()
    )
    # §2.1 H3 / §2.3: accepted proposal rows ARE grants — the grant of record.
    grants: dict[int, Day] = accepted_sacrifice_grants(db, week)
    grants.update(sacrifice_grants or {})
    return SolverInput(
        week_monday=week.monday_date,
        roster=roster,
        constraints=constraints,
        free_day_pins=free_day_pins or {},
        sacrifice_grants=grants,
        prior_state=_load_prior_state(db),
        weights=DEFAULT_WEIGHTS,
    )


def run_solve(
    db: DbSession,
    week: Week,
    free_day_pins: Mapping[int, Day] | None = None,
    actor: User | None = None,
) -> SolverResult:
    """Solve `week` and persist the outcome (§3.2, §8).

    Always stamps `solved_at` and moves an OPEN week to `solved` (the solve ran,
    the window is closed, §3.2): "the solver has run → status=solved". A `locked`
    week is never downgraded, and a re-solve of an already-`solved` week stays
    `solved` — the OPEN→SOLVED transition is one-way here. On a feasible result,
    replaces the generated assignment rows with the new schedule plus the fixed H5
    weekend template. On INFEASIBLE, it CLEARS the generated rows and leaves the
    blocking constraints on the result for the §2.3 sacrifice flow — the
    feasible/infeasible distinction is carried by whether solver rows were written,
    not by the status, so a week parked on a conflict must not keep the stale rows
    of an earlier feasible solve. Leaving them would let §3.3's "never published
    with an unresolved conflict" be violated by publishing that stale schedule.

    `actor` is the human who triggered the solve (admin/root), or None for the
    §11 cron. Every solve is audited (§5 audit log): the transition is recorded in
    the same transaction that stamps `solved_at`, so the log never lies about a
    window that closed.
    """
    roster = build_roster(db)
    # §2.3 (v1.6): grants are NOT a parameter here — build_solver_input reads the
    # week's grant of record (accepted proposals) itself, so every solve path
    # (cron, manual, accept) carries them without any caller remembering to.
    result = solve(build_solver_input(db, week, roster, free_day_pins))

    if result.status is SolverStatus.INFEASIBLE:
        # The week is parked on an unresolved conflict: drop any schedule an earlier
        # feasible solve left behind, so "no solver rows" honestly means "unresolved"
        # and a stale schedule can never be published (§3.3).
        _clear_generated_assignments(db, week)
    else:
        _replace_generated_assignments(db, week, roster, result)
    week.solved_at = utcnow()
    if week.status is WeekStatus.OPEN:
        week.status = WeekStatus.SOLVED
    audit.record(
        db,
        actor,
        audit.ACTION_SOLVE,
        "week",
        week.id,
        {"monday": week.monday_date.isoformat(), "status": result.status.value},
    )
    db.commit()
    return result


def _load_prior_state(db: DbSession) -> dict[int, PriorSlot]:
    """§2.2 cross-week seed from persisted `solver_state`.

    A stored row with a NULL `last_worked_slot` is the FULL_DAY boundary the single
    am/pm column cannot hold (the two full-weekend workers); a present am/pm value
    maps straight across. A user with no row is absent → no boundary term. On a
    first-ever week the table is empty, so every worker is absent — the known,
    carried-forward first-week limitation of the S2 spread term.
    """
    prior: dict[int, PriorSlot] = {}
    for st in db.scalars(select(SolverState)).all():
        if st.last_worked_slot is None:
            prior[st.user_id] = PriorSlot.FULL_DAY
        else:
            prior[st.user_id] = PriorSlot(st.last_worked_slot.value)
    return prior


def _clear_generated_assignments(db: DbSession, week: Week) -> None:
    """Drop this week's solver + weekend-template rows. Swap/override rows authored
    elsewhere (§4/§5) survive — this module only owns what it generated."""
    db.execute(
        delete(Assignment).where(
            Assignment.week_id == week.id, Assignment.source.in_(_GENERATED_SOURCES)
        )
    )


def _replace_generated_assignments(
    db: DbSession, week: Week, roster: tuple[WorkerRef, ...], result: SolverResult
) -> None:
    """Idempotent (re)generate: drop this week's solver + weekend-template rows and
    write the fresh set. Swap/override rows are left untouched (§4/§5)."""
    _clear_generated_assignments(db, week)
    for a in result.assignments:
        db.add(
            Assignment(
                week_id=week.id,
                day=a.day,
                slot=a.slot,
                role=a.role,
                user_id=a.worker_id,
                source=AssignmentSource.SOLVER,
            )
        )
    for wa in emit_weekend_template(roster, week.monday_date):
        db.add(
            Assignment(
                week_id=week.id,
                day=wa.day,
                slot=wa.slot,
                role=wa.role,
                user_id=wa.worker_id,
                source=AssignmentSource.WEEKEND_TEMPLATE,
            )
        )
