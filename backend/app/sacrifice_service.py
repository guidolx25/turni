"""The §2.3 sacrifice flow — infeasibility resolved, never silently.

When a solve is INFEASIBLE, the blocking hard constraints are already named (via
assumption literals, §8). This module turns that into the §2.3 conversation:

1. **Probe before proposing.** For each core worker named in the conflict, re-solve
   once with their free-day domain extended to the conflicted day (`free_day_pins`
   → `_free_domain`). If that is feasible, we *know* accepting will work — so we
   propose it. No dead-end proposals where a worker consents and the re-solve fails
   anyway (which would corrode trust in the offer).
2. **Propose to that worker:** "Move your free day to {day}?" (in-app now; email
   later — same `notify()` fan-out). Explicit accept/decline; never auto-resolved.
3. **Accept →** re-solve with the free day pinned (feasible by construction) and
   publish. **Decline, or no worker's move helps →** escalate to the admin (§2.3),
   which subsumes the pin-only case: it escalates through the probe failing, not
   through skipping the flow.

Escalation notifies the *visible* admin only — a role-based fan-out, so root is
excluded (§5); Matteo-as-worker still gets his own per-user notifications elsewhere.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.enums import Day, SacrificeStatus
from app.models import SacrificeProposal, User, Week
from app.notifications import (
    EVENT_SACRIFICE_ESCALATED,
    EVENT_SACRIFICE_PROPOSED,
    EVENT_SACRIFICE_RESOLVED,
    notify,
)
from app.publish_service import publish_week
from app.solve_service import build_roster, build_solver_input, run_solve
from app.solver import PersonalConstraint, SolverResult, SolverStatus, WorkerRef, solve
from app.visibility import admin_recipients

# Calendar order for a deterministic probe sequence over candidate days.
_DAY_INDEX: dict[Day, int] = {d: i for i, d in enumerate(Day)}

ERROR_PROPOSAL_NOT_FOUND = "sacrifice_not_found"
ERROR_PROPOSAL_RESOLVED = "sacrifice_already_resolved"


def open_sacrifice(db: DbSession, week: Week, result: SolverResult) -> SacrificeProposal | None:
    """§2.3 steps 1–2: from an INFEASIBLE result, probe and either open ONE
    proposal to a core worker or escalate to the admin. Returns the proposal, or
    None when nothing was resolvable by a free-day move (escalated instead)."""
    roster = build_roster(db)
    by_id = {w.id: w for w in roster}
    candidates = sorted(
        {
            (c.worker_id, c.day)
            for c in result.blocking_constraints
            if by_id.get(c.worker_id) is not None and by_id[c.worker_id].is_core
        },
        key=lambda pair: (pair[0], _DAY_INDEX[pair[1]]),
    )
    for worker_id, day in candidates:
        probe = solve(build_solver_input(db, week, roster, free_day_pins={worker_id: day}))
        if probe.status is not SolverStatus.INFEASIBLE:
            return _create_proposal(db, week, worker_id, day)

    # §2.3: no free-day move restores coverage — escalate to the admin WITH the
    # conflict explanation. The blocking constraints are in hand here, so we build
    # the note now rather than discarding them.
    _escalate(
        db,
        week,
        outcome="escalated",
        conflict_note=_blocking_note(by_id, result.blocking_constraints),
    )
    db.commit()
    return None


def accept_sacrifice(db: DbSession, proposal: SacrificeProposal, actor: User) -> SacrificeProposal:
    """§2.3 step 3 (accept): re-solve with the free day pinned, then publish.

    Feasible by construction (the proposal was probed), but the INFEASIBLE branch
    is kept honest: it never publishes an unsolvable week — it escalates instead."""
    _require_pending(proposal)
    proposal.status = SacrificeStatus.ACCEPTED
    week = proposal.week
    result = run_solve(
        db, week, free_day_pins={proposal.user_id: proposal.proposed_free_day}, actor=actor
    )
    audit.record(
        db,
        actor,
        audit.ACTION_SACRIFICE,
        "sacrifice_proposal",
        proposal.id,
        {"transition": "accept"},
    )

    if result.status is SolverStatus.INFEASIBLE:
        # State changed since the probe (a late edit or a competing solve): the
        # accepted pin no longer solves. Escalate WITH the conflict, never publish.
        _escalate(db, week, outcome="escalated", conflict_note=proposal.conflict_note)
    else:
        publish_week(db, week, actor)
        notify(
            db,
            db.get(User, proposal.user_id),
            EVENT_SACRIFICE_RESOLVED,
            {
                "week": week.monday_date.isoformat(),
                "outcome": "accepted",
                "free_day": proposal.proposed_free_day.value,
            },
        )
    db.commit()
    return proposal


def decline_sacrifice(db: DbSession, proposal: SacrificeProposal, actor: User) -> SacrificeProposal:
    """§2.3 step 3 (decline): escalate to the admin with the conflict, unresolved."""
    _require_pending(proposal)
    proposal.status = SacrificeStatus.DECLINED
    audit.record(
        db,
        actor,
        audit.ACTION_SACRIFICE,
        "sacrifice_proposal",
        proposal.id,
        {"transition": "decline"},
    )
    # §2.3: forward the conflict explanation the proposal was probed against.
    _escalate(db, proposal.week, outcome="declined", conflict_note=proposal.conflict_note)
    db.commit()
    return proposal


def _create_proposal(db: DbSession, week: Week, worker_id: int, day: Day) -> SacrificeProposal:
    proposal = SacrificeProposal(
        week_id=week.id,
        user_id=worker_id,
        proposed_free_day=day,
        status=SacrificeStatus.PENDING,
        conflict_note=(
            f"No feasible schedule honors the current hard requests; "
            f"offering {day.value} as a full free day."
        ),
    )
    db.add(proposal)
    db.flush()  # assign an id for the notification payload
    audit.record(
        db,
        None,  # system: the proposal is opened by the (cron/admin-triggered) solve
        audit.ACTION_SACRIFICE,
        "sacrifice_proposal",
        proposal.id,
        {"transition": "propose", "user_id": worker_id, "proposed_free_day": day.value},
    )
    notify(
        db,
        db.get(User, worker_id),
        EVENT_SACRIFICE_PROPOSED,
        {
            "proposal_id": proposal.id,
            "week": week.monday_date.isoformat(),
            "proposed_free_day": day.value,
        },
    )
    db.commit()
    return proposal


def _blocking_note(by_id: dict[int, WorkerRef], blocking: tuple[PersonalConstraint, ...]) -> str:
    """A human-readable summary of the hard requests that make the week INFEASIBLE,
    for the §2.3 admin escalation. English for now — a tracked Phase 4/5 i18n
    carry-forward, consistent with the existing `conflict_note` string."""
    parts = [
        f"{by_id[c.worker_id].display_name} {c.day.value} {c.slot.value}"
        for c in blocking
        if c.worker_id in by_id
    ]
    joined = ", ".join(parts) if parts else "unattributed hard requests"
    return f"No feasible schedule honors the current hard requests; conflicting: {joined}."


def _escalate(db: DbSession, week: Week, outcome: str, conflict_note: str | None) -> None:
    """§2.3: hand an UNRESOLVED conflict to the admin WITH its explanation.

    Role-based fan-out → root is excluded (§5); a distinct escalation event keeps
    this hand-off from being conflated with a `sacrifice_resolved` resolution.
    """
    payload = {
        "week": week.monday_date.isoformat(),
        "outcome": outcome,
        "conflict_note": conflict_note,
    }
    audit.record(
        db, None, audit.ACTION_SACRIFICE, "week", week.id, {"transition": "escalate", **payload}
    )
    for admin in admin_recipients(db):
        notify(db, admin, EVENT_SACRIFICE_ESCALATED, payload)


def _require_pending(proposal: SacrificeProposal) -> None:
    if proposal.status is not SacrificeStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_PROPOSAL_RESOLVED)
