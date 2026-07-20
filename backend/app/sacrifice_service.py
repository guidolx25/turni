"""The §2.3 sacrifice flow — infeasibility resolved, never silently.

When a solve is INFEASIBLE, the blocking hard constraints are already named (via
assumption literals, §8). This module turns that into the §2.3 conversation:

1. **Probe before proposing.** For each core worker named in the conflict, re-solve
   once carrying a **sacrifice grant** for the conflicted day (extending that one
   worker's H3 free-day domain to `Mon–Thu ∪ {day}`) together with a pin forcing
   their free day onto it. If that is feasible, we *know* accepting will work — so
   we propose it. No dead-end proposals where a worker consents and the re-solve
   fails anyway (which would corrode trust in the offer).

   The grant is load-bearing and must not be reduced to a bare pin (§2.3). A pin
   alone only *adds* `free[u][d] = 1` to an otherwise unchanged model, so the
   probe's feasible region would be a SUBSET of the plain solve's — an INFEASIBLE
   week would stay INFEASIBLE under every pin and this branch could never fire.

   What is traded is the worker's weekday free-day PLACEMENT, never their hard
   request: H7 stays inviolable and an accepted proposal still honors the hard
   unavailability in full (§2.3 "What is being traded").
2. **Propose to that worker:** "Move your free day to {day}?" (in-app now; email
   later — same `notify()` fan-out). Explicit accept/decline; never auto-resolved.
3. **Accept →** re-solve with the grant AND the pin (feasible by construction) and
   publish. **Decline, or no worker's move helps →** escalate to the admin (§2.3):
   it escalates through the probe failing, not through skipping the flow.

Escalation notifies the *visible* admin only — a role-based fan-out, so root is
excluded (§5); Matteo-as-worker still gets his own per-user notifications elsewhere.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
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
from app.solver import (
    SOLVER_DAYS,
    PersonalConstraint,
    SolverResult,
    SolverStatus,
    WorkerRef,
    solve,
)
from app.visibility import admin_recipients

# Calendar order for a deterministic probe sequence over candidate days.
logger = logging.getLogger(__name__)

_DAY_INDEX: dict[Day, int] = {d: i for i, d in enumerate(Day)}

ERROR_PROPOSAL_NOT_FOUND = "sacrifice_not_found"
ERROR_PROPOSAL_RESOLVED = "sacrifice_already_resolved"


def open_sacrifice(db: DbSession, week: Week, result: SolverResult) -> SacrificeProposal | None:
    """§2.3 steps 1–2: from an INFEASIBLE result, probe and either open ONE
    proposal to a core worker or escalate to the admin. Returns the proposal, or
    None when nothing was resolvable by a free-day move (escalated instead)."""
    roster = build_roster(db)
    by_id = {w.id: w for w in roster}
    # §10: the enumerated unsat core (the conflicting hard requests, from the §8
    # assumption literals) rendered readable. Computed once and carried on every
    # path — the proposal's conflict_note (so decline/accept-infeasible forward it)
    # and the immediate escalation below — so the admin always has the minimal core.
    conflict_note = _blocking_note(by_id, result.blocking_constraints)
    # §2.3: a proposal must never loop back to someone who already answered it for
    # THIS week — whatever the answer, and even for a different day (conservative
    # per-worker exclusion). DECLINED is the obvious case. ACCEPTED matters too: the
    # grant is call-scoped, so if an accepted re-solve came back INFEASIBLE the week
    # is left SOLVED with the row still ACCEPTED, and the next solve carries no grant
    # and is deterministically INFEASIBLE again — without this the same worker would
    # be re-offered the same day, with a duplicate `sacrifice_proposed` notice.
    # With both out of the probe set, a re-solve either proposes to a different
    # not-yet-asked worker whose move helps, or falls through to _escalate below.
    answered = set(
        db.scalars(
            select(SacrificeProposal.user_id).where(
                SacrificeProposal.week_id == week.id,
                SacrificeProposal.status.in_((SacrificeStatus.DECLINED, SacrificeStatus.ACCEPTED)),
            )
        )
    )
    # H3 + §2.3 sacrifice grant: a conflicted day is a candidate iff a grant could
    # make it a legal free day — the GENERAL rule, `day ∈ SOLVER_DAYS` (Mon–Fri),
    # since that is exactly what `free_day_domain` will extend to. The §2.3
    # corollary then falls out rather than being special-cased:
    #   - Mon–Thu are already in the default domain, so the grant is a no-op and the
    #     probe reduces to the plain solve plus a pin. A pin only ADDS free[u][d]=1,
    #     so the probe's feasible region is a subset: an INFEASIBLE week stays
    #     INFEASIBLE. Holds for slot-level and full-day requests alike;
    #   - Friday is the one day H4 forces worked that the grant can free — the only
    #     day where extending the domain changes the outcome;
    #   - Sat/Sun have no solver variables at all (H5 template), so they are not in
    #     SOLVER_DAYS, yield no candidate, and fall through to the escalation below.
    # No literal Friday check appears anywhere in this filter.
    candidates = sorted(
        {
            (c.worker_id, c.day)
            for c in result.blocking_constraints
            if by_id.get(c.worker_id) is not None
            and by_id[c.worker_id].is_core
            and c.day in SOLVER_DAYS
            and c.worker_id not in answered
        },
        key=lambda pair: (pair[0], _DAY_INDEX[pair[1]]),
    )
    for worker_id, day in candidates:
        # §2.3: probe with the GRANT (widening this one worker's H3 domain to the
        # conflicted day) plus the pin that lands their free day on it — exactly
        # what accept_sacrifice will re-solve, so a feasible probe is a promise.
        probe = solve(
            build_solver_input(
                db,
                week,
                roster,
                free_day_pins={worker_id: day},
                sacrifice_grants={worker_id: day},
            )
        )
        if probe.status is not SolverStatus.INFEASIBLE:
            return _create_proposal(db, week, worker_id, day, conflict_note)

    # §2.3: no free-day move restores coverage — escalate to the admin WITH the
    # enumerated-core explanation. The blocking constraints are in hand here, so we
    # carry the core rather than discarding it.
    _escalate(db, week, outcome="escalated", conflict_note=conflict_note)
    db.commit()
    return None


def accept_sacrifice(db: DbSession, proposal: SacrificeProposal, actor: User) -> SacrificeProposal:
    """§2.3 step 3 (accept): re-solve with the free day granted AND pinned, then publish.

    The pin forces the free day onto the offered day; the grant (H3) is what makes
    that day part of the worker's domain in the first place, so the two must travel
    together — a pin without its grant would be silently dropped by the model and
    the re-solve would not reproduce the probe.

    The worker's hard request is untouched: it is still enforced as an H7 assumption
    on this re-solve (§2.3 — the trade is the free-day placement, never the request).

    Feasible by construction (the proposal was probed), but the INFEASIBLE branch
    is kept honest: it never publishes an unsolvable week — it escalates instead."""
    _require_pending(proposal)
    proposal.status = SacrificeStatus.ACCEPTED
    week = proposal.week
    result = run_solve(
        db,
        week,
        free_day_pins={proposal.user_id: proposal.proposed_free_day},
        actor=actor,
        sacrifice_grants={proposal.user_id: proposal.proposed_free_day},
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


def _create_proposal(
    db: DbSession, week: Week, worker_id: int, day: Day, conflict_note: str
) -> SacrificeProposal:
    # §10: store the enumerated unsat core (the conflicting hard requests) as the
    # proposal's conflict_note, not an "offering {day}" blurb. decline_sacrifice
    # and the accept-infeasible path forward proposal.conflict_note to the admin,
    # so the minimal core reaches the escalation on every path. It also surfaces to
    # the worker (SacrificeProposalOut.conflict_note) — a kept improvement, telling
    # them *why* they were asked. The offered day already rides its own field.
    proposal = SacrificeProposal(
        week_id=week.id,
        user_id=worker_id,
        proposed_free_day=day,
        status=SacrificeStatus.PENDING,
        conflict_note=conflict_note,
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
    """§2.3/§10: hand an UNRESOLVED conflict to the admin WITH its explanation.

    Uniform `{week, outcome, conflict_note}` payload across all three call sites
    (open_sacrifice-immediate, accept-infeasible, decline). The §10 minimal unsat
    core is delivered as the enumerated conflicting hard requests within
    `conflict_note` (the §8 assumption-literal core rendered readable) — no §6
    column is added; §6 sacrifice_proposals is unchanged, only §10 was amended.

    Role-based fan-out → ONLY `admin_recipients(db)` receive it, and root is
    excluded there via `visible_users_stmt` (§5); NO worker-facing notification
    fires. Escalation does NOT change `week.status`: the week stays `solved`
    (unpublished, worker-invisible) for the admin to resolve (§3.3). A distinct
    escalation event keeps this hand-off from being conflated with a
    `sacrifice_resolved` resolution.
    """
    payload = {
        "week": week.monday_date.isoformat(),
        "outcome": outcome,
        "conflict_note": conflict_note,
    }
    audit.record(
        db, None, audit.ACTION_SACRIFICE, "week", week.id, {"transition": "escalate", **payload}
    )
    recipients = admin_recipients(db)
    if not recipients:
        # Never escalate into the void: with no visible admin the week is parked in
        # `solved` with nobody told it needs resolving, so make the gap loud rather
        # than leaving only an audit row (§2.3 step 4). Mirrors the same guard on
        # the weekend-hard escalation path.
        logger.error(
            "Week %s escalated (%s) but has no visible admin recipient; it is parked "
            "in `solved` with no one notified. Conflict: %s",
            week.monday_date.isoformat(),
            outcome,
            conflict_note,
        )
        return
    for admin in recipients:
        notify(db, admin, EVENT_SACRIFICE_ESCALATED, payload)


def _require_pending(proposal: SacrificeProposal) -> None:
    if proposal.status is not SacrificeStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_PROPOSAL_RESOLVED)
