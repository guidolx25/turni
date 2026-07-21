"""The §2.3 sacrifice flow — infeasibility resolved, never silently.

When a solve is INFEASIBLE, the blocking hard constraints are already named (via
assumption literals, §8). This module turns that into the §2.3 conversation:

1. **Probe before proposing.** For each core worker named in the conflict, re-solve
   once carrying a **sacrifice grant** for the conflicted day (extending that one
   worker's H3 free-day domain to `role-domain ∪ {day}`) together with a pin forcing
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
    # assumption literals) as STRUCTURED DATA — {worker_id, day, slot} items the §9
    # dictionaries render in the viewer's language. Computed once and carried on
    # every path — the proposal's `conflict` (so decline/accept-infeasible forward
    # it) and the immediate escalation below — so the admin always has the core.
    conflict = _blocking_core(result.blocking_constraints)
    # §2.3: a proposal must never loop back to someone who already answered it for
    # THIS week — whatever the answer, and even for a different day (conservative
    # per-worker exclusion). DECLINED is the obvious case. ACCEPTED is a logic
    # error made impossible: an accepted row is the persisted GRANT OF RECORD
    # (v1.6), carried by every subsequent solve, so that worker's conflict is
    # already structurally solved — if the week is STILL infeasible it is
    # infeasible for a DIFFERENT core, and the fix is proposing to a different
    # not-yet-asked worker (the normal iterative case) or falling through to
    # _escalate below, never re-offering this one. The §6 (week_id, user_id)
    # unique key backs the same rule at the schema level.
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
    # reachable-days table then falls out rather than being special-cased:
    #   - a day already inside the holder's H3(b) ROLE domain makes the grant a
    #     no-op, so the probe reduces to the plain solve plus a pin. A pin only
    #     ADDS free[u][d]=1, so the probe's feasible region is a subset: an
    #     INFEASIBLE week stays INFEASIBLE, and the candidate falls through to the
    #     escalation below. Holds for slot-level and full-day requests alike;
    #   - the days OUTSIDE that role domain are the ones a grant can actually free,
    #     and v1.12 makes them per-role: Wed/Thu/Fri for a spiaggino (domain
    #     Mon/Tue), Mon/Thu/Fri for a bagnino (domain Tue/Wed). Six reachable cells,
    #     not the single Friday of the superseded corollary;
    #   - Sat/Sun have no solver variables at all (H5 template), so they are not in
    #     SOLVER_DAYS, yield no candidate, and fall through to the escalation below.
    # The filter is purely structural: it names no day, so which cells are reachable
    # is decided entirely by `free_day_domain` and the probe, and this code needed no
    # change when v1.12 replaced the uniform Mon–Thu domain with per-role domains.
    # It is also why the two systematically-infeasible cases in §2.3 (one worker with
    # two out-of-domain requests; both same-role workers on the same out-of-domain
    # day, which H3(c) forbids) need no special case here — their probes simply come
    # back INFEASIBLE and the loop escalates.
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
            return _create_proposal(db, week, worker_id, day, conflict)

    # §2.3: no free-day move restores coverage — escalate to the admin WITH the
    # enumerated-core explanation. The blocking constraints are in hand here, so we
    # carry the core rather than discarding it.
    _escalate(db, week, outcome="escalated", conflict=conflict)
    db.commit()
    return None


def accept_sacrifice(db: DbSession, proposal: SacrificeProposal, actor: User) -> SacrificeProposal:
    """§2.3 step 3 (accept): re-solve with the free day granted AND pinned, then publish.

    Marking the row ACCEPTED is what issues the grant: the accepted proposal is
    the GRANT OF RECORD (§2.1 H3, v1.6), read by `build_solver_input` on this
    re-solve and on every later solve of the week — the flip precedes `run_solve`
    below so the very solve that answers the acceptance already reads it from the
    row, not from a call-scoped argument. The pin forces the free day onto the
    offered day for THIS re-solve, reproducing the probe exactly.

    The worker's hard request is untouched: it is still enforced as an H7 assumption
    on this re-solve (§2.3 — the trade is the free-day placement, never the request).

    Feasible by construction (the proposal was probed), but the INFEASIBLE branch
    is kept honest: it never publishes an unsolvable week — it escalates instead."""
    _require_pending(proposal)
    proposal.status = SacrificeStatus.ACCEPTED
    # The session runs autoflush=False, so make the grant of record visible to
    # build_solver_input's accepted-proposals read BEFORE the re-solve — without
    # this the flip sits unflushed and the very solve that answers the acceptance
    # would miss its own grant.
    db.flush()
    week = proposal.week
    result = run_solve(
        db,
        week,
        free_day_pins={proposal.user_id: proposal.proposed_free_day},
        actor=actor,
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
        _escalate(db, week, outcome="escalated", conflict=proposal.conflict)
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
    _escalate(db, proposal.week, outcome="declined", conflict=proposal.conflict)
    db.commit()
    return proposal


def _create_proposal(
    db: DbSession, week: Week, worker_id: int, day: Day, conflict: list[dict[str, object]]
) -> SacrificeProposal:
    # §10: store the enumerated unsat core (the conflicting hard requests) as the
    # proposal's `conflict`, not an "offering {day}" blurb. decline_sacrifice
    # and the accept-infeasible path forward proposal.conflict to the admin,
    # so the minimal core reaches the escalation on every path. It also surfaces to
    # the worker (SacrificeProposalOut.conflict) — a kept improvement, telling
    # them *why* they were asked. The offered day already rides its own field.
    proposal = SacrificeProposal(
        week_id=week.id,
        user_id=worker_id,
        proposed_free_day=day,
        status=SacrificeStatus.PENDING,
        conflict=conflict,
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


def _blocking_core(blocking: tuple[PersonalConstraint, ...]) -> list[dict[str, object]]:
    """The §8 minimal unsat core as data for §6 `sacrifice_proposals.conflict`:
    one {worker_id, day, slot} item per blocking hard request. No display names
    and no prose — rendering (and localization) is the §9 dictionaries' job.
    Closes the Phase 3 carry-forward that persisted a pre-formatted English
    sentence the dictionaries could never retroactively localize."""
    return [{"worker_id": c.worker_id, "day": c.day.value, "slot": c.slot.value} for c in blocking]


def _escalate(
    db: DbSession, week: Week, outcome: str, conflict: list[dict[str, object]] | None
) -> None:
    """§2.3/§10: hand an UNRESOLVED conflict to the admin WITH its explanation.

    Uniform `{week, outcome, conflict}` payload across all three call sites
    (open_sacrifice-immediate, accept-infeasible, decline). The §10 minimal unsat
    core is delivered as the enumerated conflicting hard requests in `conflict`
    (the §8 assumption-literal core as {worker_id, day, slot} data, v1.5 —
    localized at render time by the §9 dictionaries, never pre-formatted).

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
        "conflict": conflict,
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
            conflict,
        )
        return
    for admin in recipients:
        notify(db, admin, EVENT_SACRIFICE_ESCALATED, payload)


def _require_pending(proposal: SacrificeProposal) -> None:
    if proposal.status is not SacrificeStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_PROPOSAL_RESOLVED)
