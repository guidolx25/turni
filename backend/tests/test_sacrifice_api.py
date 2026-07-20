"""The §2.3 sacrifice flow end to end (§7 `/sacrifice/*`, §2.3, §10).

Two distinct lifecycle endings are covered:

* **Escalation** — the solve is INFEASIBLE and the §2.3 probe finds no free-day
  move that absorbs the conflict, so no proposal is opened and the visible admin
  is escalated to with the enumerated unsat core. The week stays `solved` (parked,
  unpublished).
* **Propose → accept/decline** — the §2.3 conversation's state machine: only the
  target worker may act, an accept re-solves with the free day granted AND pinned
  and publishes, a decline escalates, and neither can happen twice.

H3 note (§2.1, v1.4): a core worker's free day defaults to Mon–Thu, and the §2.3
flow may issue that ONE worker a **sacrifice grant** widening their domain to
`Mon–Thu ∪ {day}`. Per the §2.3 corollary, Friday is the only day where a grant
changes anything — Mon–Thu self-place through H4, Sat/Sun escalate at submission
under H5. So a hard Friday request opens a proposal **iff** the Friday-extended
probe is feasible, and escalates otherwise. Both branches are covered here:

* `test_h3_hard_friday_request_opens_a_friday_free_day_proposal` — probe feasible.
* `test_h3_friday_conflict_with_infeasible_probe_escalates` — probe infeasible.

The trade is the free-day PLACEMENT, never the hard request: an accepted proposal
still honors H7 in full. That is asserted end-to-end on a real `/admin/solve` in
`tests/test_full_week_simulation.py`.

Fixture note: `_force_proposal` seeds a proposal directly via `_create_proposal`
so the state-machine tests below (authorization, one-shot transitions, audit rows,
re-solve guards) can exercise the accept/decline machinery on a plain feasible
week, independent of what made a proposal open. It is DOWNSTREAM coverage only —
the propose branch itself is reachable through `/admin/solve` and is proven there.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.audit import ACTION_SACRIFICE
from app.enums import ConstraintKind, ConstraintSlot, Day, SacrificeStatus, WeekStatus
from app.models import Assignment, AuditLog, Constraint, Notification, SacrificeProposal, Week
from app.notifications import (
    EVENT_SACRIFICE_ESCALATED,
    EVENT_SACRIFICE_PROPOSED,
    EVENT_SACRIFICE_RESOLVED,
    EVENT_SCHEDULE_PUBLISHED,
)
from app.routers.admin import ERROR_SACRIFICE_PENDING
from app.sacrifice_service import _create_proposal
from app.scheduling import get_or_create_week
from app.solve_service import run_solve
from app.solver import FREE_DAYS
from tests.factories import PASSWORD, create_full_roster


def _future_monday(weeks_ahead: int = 2) -> dt.date:
    today = dt.datetime.now(dt.UTC).date()
    next_monday = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)
    return next_monday + dt.timedelta(weeks=weeks_ahead - 1)


def login(client: TestClient, username: str) -> None:
    resp = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _hard(session: DbSession, user_id: int, week: Week, day: Day, slot=ConstraintSlot.FULL_DAY):
    session.add(
        Constraint(user_id=user_id, week_id=week.id, day=day, slot=slot, kind=ConstraintKind.HARD)
    )
    session.commit()


def _solve(client: TestClient, monday: dt.date):
    return client.post("/admin/solve", params={"week": monday.isoformat()})


def _force_proposal(
    session: DbSession,
    roster: dict,
    monday: dt.date,
    *,
    worker: str = "pasha",
    day: Day = Day.THU,
) -> tuple[Week, SacrificeProposal]:
    """A feasibly-SOLVED week carrying one PENDING §2.3 proposal.

    Seeded through `sacrifice_service._create_proposal` — the same function
    `open_sacrifice` calls once its probe succeeds — so the tests below can drive
    the accept/decline state machine without also having to construct an
    infeasibility. The week is solved first so it is genuinely parked in `solved`,
    the state a real proposal is opened from. The real propose branch (INFEASIBLE
    solve → probe → proposal) is covered from `/admin/solve` in
    `test_h3_hard_friday_request_opens_a_friday_free_day_proposal` and end-to-end
    in `tests/test_full_week_simulation.py`.
    """
    assert day in FREE_DAYS, "a proposal may only ever offer a Mon–Thu free day (H3)"
    week = get_or_create_week(session, monday)
    run_solve(session, week)  # feasible → OPEN→SOLVED, unpublished
    target = roster[worker]
    proposal = _create_proposal(
        session,
        week,
        target.id,
        day,
        conflict_note=(
            "No feasible schedule honors the current hard requests; "
            f"conflicting: {target.display_name} {day.value} full_day."
        ),
    )
    return week, proposal


# --- §2.3: the two branches of a hard Friday request ------------------------
#
# Friday is the only day a sacrifice grant can change (§2.3 corollary), so it is
# where both branches of step 2 are exercised: probe feasible → propose; probe
# infeasible → escalate. Which branch fires is decided by the probe alone, never
# by a literal day check, so both must stay covered.


def test_h3_hard_friday_request_opens_a_friday_free_day_proposal(
    client: TestClient, session: DbSession
) -> None:
    """§2.1 H3 (v1.4) + §2.3 step 2: Pasha hard-off Friday makes the plain solve
    INFEASIBLE — H4 forces Friday worked and his DEFAULT free-day domain stops at
    Thursday. The flow then probes with a Friday sacrifice grant (`Mon–Thu ∪ {Fri}`)
    plus the matching pin; that probe is feasible, so ONE proposal is opened to
    Pasha offering Friday as his free day.

    Nothing is resolved silently (§2.3 step 4): the week stays `solved` and
    unpublished until Pasha answers, and the admin is NOT escalated to yet — the
    conversation is his to have first.
    """
    roster = create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    _hard(session, roster["pasha"].id, week, Day.FRI)

    login(client, "mattia")
    resp = _solve(client, monday)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "infeasible"
    # §8: the unsat core attributes the conflict to the requesting worker.
    blocking = resp.json()["blocking_constraints"]
    assert any(b["worker_id"] == roster["pasha"].id and b["day"] == "fri" for b in blocking), (
        f"the core must name Pasha's Friday request: {blocking}"
    )

    # (a) Exactly one proposal, to the named worker, offering the conflicted day.
    proposals = session.scalars(select(SacrificeProposal)).all()
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.user_id == roster["pasha"].id
    assert proposal.status is SacrificeStatus.PENDING
    assert proposal.proposed_free_day is Day.FRI, (
        "§2.3: the grant is issued for the day named in the blocking hard request"
    )
    assert proposal.conflict_note, "the worker is told why they were asked"

    # (b) The target worker — and only they — is notified, with the proposal id.
    notes = session.scalars(
        select(Notification).where(Notification.event_type == EVENT_SACRIFICE_PROPOSED)
    ).all()
    assert [n.user_id for n in notes] == [roster["pasha"].id]
    assert notes[0].payload.get("proposed_free_day") == Day.FRI.value
    assert notes[0].payload.get("proposal_id") == proposal.id

    # (c) Not resolved silently and not escalated: no schedule, no publish, no
    #     admin hand-off while the offer is still open.
    assert session.scalars(select(Assignment).where(Assignment.week_id == week.id)).all() == []
    assert (
        session.scalars(
            select(Notification).where(Notification.event_type == EVENT_SACRIFICE_ESCALATED)
        ).all()
        == []
    ), "the admin is escalated to only if the conversation fails"
    assert (
        session.scalars(
            select(Notification).where(Notification.event_type == EVENT_SACRIFICE_RESOLVED)
        ).all()
        == []
    )
    session.refresh(week)
    assert week.status is WeekStatus.SOLVED


def test_h3_hard_friday_request_leaves_the_week_unpublishable_until_answered(
    client: TestClient, session: DbSession
) -> None:
    """§3.3: a week parked on an OPEN §2.3 conversation cannot be published away —
    `/admin/publish` refuses it with `sacrifice_pending`, and it stays `solved`."""
    roster = create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    _hard(session, roster["pasha"].id, week, Day.FRI)

    login(client, "mattia")
    assert _solve(client, monday).json()["status"] == "infeasible"

    resp = client.post("/admin/publish", params={"week": monday.isoformat()})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == ERROR_SACRIFICE_PENDING
    session.expire_all()
    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.SOLVED


def test_h3_friday_conflict_with_infeasible_probe_escalates(
    client: TestClient, session: DbSession
) -> None:
    """§2.3 last line: "a Friday conflict whose extended probe is *still*
    infeasible produces no proposal and escalates". The counter-case to the test
    above — the branch is chosen by the probe, not by the day.

    Compounded so the Friday-extended probe genuinely fails on COVERAGE: Pasha is
    hard-off Friday AND the jolly is hard-off Friday. Granting Pasha a Friday free
    day leaves Friday needing two spiaggino slots with only Amir available, and H4
    gives him exactly one — so H1 cannot be met and the probe is INFEASIBLE.

    The intended-reason guard: the SAME Pasha request without the jolly's
    constraint DOES open a proposal (the test above, identical fixture otherwise),
    so it is the added Friday conflict that closes the branch, not an incidental
    difference in the setup.
    """
    roster = create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    _hard(session, roster["pasha"].id, week, Day.FRI)
    _hard(session, roster["mattia"].id, week, Day.FRI)  # the jolly cannot absorb it

    login(client, "mattia")
    resp = _solve(client, monday)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "infeasible"

    # No proposal is opened — the probe found no move that works.
    assert session.scalars(select(SacrificeProposal)).all() == []
    # The worker is told nothing; there is nothing to accept.
    pasha_notes = session.scalars(
        select(Notification).where(Notification.user_id == roster["pasha"].id)
    ).all()
    assert not any(n.event_type == EVENT_SACRIFICE_PROPOSED for n in pasha_notes)
    assert not any(n.event_type == EVENT_SACRIFICE_RESOLVED for n in pasha_notes)

    # §2.3 step 3: the visible admin holds the conflict, with the enumerated core.
    session.refresh(week)
    _assert_minimal_core_escalation(session, roster, week, expect_in_note=("fri",))

    # §3.3: nothing to publish — no proposal is pending, and no solver rows exist.
    assert session.scalars(select(Assignment).where(Assignment.week_id == week.id)).all() == []
    resp = client.post("/admin/publish", params={"week": monday.isoformat()})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] != ERROR_SACRIFICE_PENDING, (
        "refused for having no feasible schedule, not for an open conversation"
    )


# --- escalation when no free-day move helps ---------------------------------


def test_unresolvable_conflict_escalates_without_a_proposal(
    client: TestClient, session: DbSession
) -> None:
    """All three bagnini hard-off Monday: no core worker's free-day move restores
    coverage, so no proposal is opened and the admin is escalated to directly."""
    roster = create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    for name in ("matteo", "francesco", "mattia"):
        _hard(session, roster[name].id, week, Day.MON)

    login(client, "mattia")
    assert _solve(client, monday).json()["status"] == "infeasible"

    assert session.scalars(select(SacrificeProposal)).all() == []  # no proposal
    admin_notes = session.scalars(
        select(Notification).where(Notification.user_id == roster["mattia"].id)
    ).all()
    escalations = [
        n
        for n in admin_notes
        if n.event_type == EVENT_SACRIFICE_ESCALATED
        and n.payload
        and n.payload.get("outcome") == "escalated"
    ]
    assert escalations, "admin must receive a no-resolvable-move escalation"
    # §2.3: the blocking constraints are forwarded as a conflict explanation, not
    # discarded — the note names the conflicting Monday requests.
    note = escalations[0].payload.get("conflict_note")
    assert note and "mon" in note.lower()


# --- escalation carries the minimal unsat core (§2.3, §10, both paths) -------


def _assert_minimal_core_escalation(
    session: DbSession, roster: dict, week: Week, expect_in_note: tuple[str, ...]
) -> None:
    """§10: exactly one `sacrifice_escalated`, to the visible admin(s) ONLY (root
    excluded); its payload carries the non-empty enumerated core naming the
    conflicting hard requests; the week stays `solved`/unpublished; and the
    escalation produced NO worker-facing notification."""
    escalations = session.scalars(
        select(Notification).where(Notification.event_type == EVENT_SACRIFICE_ESCALATED)
    ).all()
    assert len(escalations) == 1  # exactly one escalation
    assert escalations[0].user_id == roster["mattia"].id  # the visible admin
    assert all(n.user_id != roster["matteo"].id for n in escalations)  # root gets none

    note = escalations[0].payload.get("conflict_note")
    assert note, "the escalation must forward the enumerated unsat core"
    lowered = note.lower()
    assert all(token in lowered for token in expect_in_note)

    session.refresh(week)
    assert week.status is WeekStatus.SOLVED  # parked, unpublished

    # The escalation is a hand-off, not a resolution: no worker-facing event fires.
    assert (
        session.scalars(
            select(Notification).where(Notification.event_type == EVENT_SCHEDULE_PUBLISHED)
        ).all()
        == []
    )
    assert (
        session.scalars(
            select(Notification).where(Notification.event_type == EVENT_SACRIFICE_RESOLVED)
        ).all()
        == []
    )


def test_decline_escalation_carries_minimal_core(client: TestClient, session: DbSession) -> None:
    """§2.3/§10 decline path: declining forwards the minimal core to the admin only."""
    roster = create_full_roster(session)
    monday = _future_monday()
    week, proposal = _force_proposal(session, roster, monday, worker="pasha", day=Day.THU)

    login(client, "pasha")
    assert client.post(f"/sacrifice/{proposal.id}/decline").status_code == 200

    session.refresh(week)
    _assert_minimal_core_escalation(session, roster, week, expect_in_note=("pasha", "thu"))


def test_no_move_escalation_carries_minimal_core(client: TestClient, session: DbSession) -> None:
    """§2.3/§10 no-resolvable-move path: the immediate escalation forwards the
    minimal core (conflicting Monday requests) to the admin only."""
    roster = create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    for name in ("matteo", "francesco", "mattia"):
        _hard(session, roster[name].id, week, Day.MON)

    login(client, "mattia")
    assert _solve(client, monday).json()["status"] == "infeasible"

    session.refresh(week)
    _assert_minimal_core_escalation(session, roster, week, expect_in_note=("mon",))


# --- propose → accept / decline (the §2.3 state machine) --------------------


def test_proposal_notifies_only_the_target_worker(client: TestClient, session: DbSession) -> None:
    """§2.3 step 2: opening a proposal addresses exactly ONE core worker — the row
    names them, they get the `sacrifice_proposed` notice carrying the proposal id,
    and nobody else is notified. The offered day is a legal H3 free day."""
    roster = create_full_roster(session)
    monday = _future_monday()
    _week, proposal = _force_proposal(session, roster, monday, worker="pasha", day=Day.THU)

    assert proposal.user_id == roster["pasha"].id
    assert proposal.status is SacrificeStatus.PENDING
    assert proposal.proposed_free_day in FREE_DAYS  # H3: never Friday or a weekend

    notes = session.scalars(
        select(Notification).where(Notification.event_type == EVENT_SACRIFICE_PROPOSED)
    ).all()
    assert [n.user_id for n in notes] == [roster["pasha"].id]  # the target, and only them
    assert notes[0].payload.get("proposal_id") == proposal.id
    assert notes[0].payload.get("proposed_free_day") == Day.THU.value


def test_accept_re_solves_pinned_and_publishes(client: TestClient, session: DbSession) -> None:
    """§2.3 step 3 (accept): the week re-solves with the accepted free day PINNED
    and is published (SOLVED→LOCKED). The pin is honored: the worker works zero
    slots on their new free day."""
    roster = create_full_roster(session)
    monday = _future_monday()
    _week, proposal = _force_proposal(session, roster, monday, worker="pasha", day=Day.THU)

    login(client, "pasha")
    resp = client.post(f"/sacrifice/{proposal.id}/accept")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"

    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.LOCKED  # published

    login(client, "pasha")
    grid = client.get("/schedule", params={"week": monday.isoformat()}).json()
    pasha_thu = [
        a for a in grid["assignments"] if a["user_id"] == roster["pasha"].id and a["day"] == "thu"
    ]
    assert pasha_thu == [], "the accepted free day must be honored by the re-solve"
    # H3 still holds for the pinned worker: Friday is worked, Thursday is the rest.
    pasha_fri = [
        a for a in grid["assignments"] if a["user_id"] == roster["pasha"].id and a["day"] == "fri"
    ]
    assert pasha_fri, "H3: the free day moved to Thursday, so Friday stays worked"

    # §10: the worker is told the outcome, naming the day they gave up.
    resolved = session.scalars(
        select(Notification).where(
            Notification.user_id == roster["pasha"].id,
            Notification.event_type == EVENT_SACRIFICE_RESOLVED,
        )
    ).all()
    assert resolved and resolved[0].payload.get("free_day") == Day.THU.value


def test_decline_escalates_to_admin_without_publishing(
    client: TestClient, session: DbSession
) -> None:
    """§2.3 step 3 (decline): the week is NOT published — it stays parked in
    `solved` — and the visible admin is escalated to with the conflict. Root is
    never a recipient of the role-based fan-out (§5)."""
    roster = create_full_roster(session)
    monday = _future_monday()
    _week, proposal = _force_proposal(session, roster, monday, worker="pasha", day=Day.THU)

    login(client, "pasha")
    resp = client.post(f"/sacrifice/{proposal.id}/decline")
    assert resp.status_code == 200
    assert resp.json()["status"] == "declined"

    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.SOLVED  # parked, not published

    admin_notes = session.scalars(
        select(Notification).where(Notification.user_id == roster["mattia"].id)
    ).all()
    escalations = [
        n
        for n in admin_notes
        if n.event_type == EVENT_SACRIFICE_ESCALATED
        and n.payload
        and n.payload.get("outcome") == "declined"
    ]
    assert escalations, "admin must receive a declined-escalation notification"
    # §2.3: the escalation carries the conflict explanation, not just an outcome.
    assert escalations[0].payload.get("conflict_note")
    matteo_notes = session.scalars(
        select(Notification).where(Notification.user_id == roster["matteo"].id)
    ).all()
    assert not any(n.event_type == EVENT_SACRIFICE_ESCALATED for n in matteo_notes)  # root excluded


# --- authorization + state --------------------------------------------------


def test_only_target_worker_may_act(client: TestClient, session: DbSession) -> None:
    """§2.3: the offer is addressed to ONE worker; a bystander cannot accept or
    decline on their behalf (404 — the proposal is not theirs to see)."""
    roster = create_full_roster(session)
    monday = _future_monday()
    _week, proposal = _force_proposal(session, roster, monday, worker="pasha", day=Day.THU)

    login(client, "amir")  # not the target
    assert client.post(f"/sacrifice/{proposal.id}/accept").status_code == 404
    assert client.post(f"/sacrifice/{proposal.id}/decline").status_code == 404

    session.expire_all()
    proposal = session.get(SacrificeProposal, proposal.id)
    assert proposal.status is SacrificeStatus.PENDING  # untouched by the bystander


def test_cannot_resolve_twice(client: TestClient, session: DbSession) -> None:
    """§2.3: accept/decline is a one-shot transition out of PENDING."""
    roster = create_full_roster(session)
    monday = _future_monday()
    _week, proposal = _force_proposal(session, roster, monday, worker="pasha", day=Day.THU)

    login(client, "pasha")
    assert client.post(f"/sacrifice/{proposal.id}/accept").status_code == 200
    resp = client.post(f"/sacrifice/{proposal.id}/accept")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "sacrifice_already_resolved"
    # A decline after an accept is refused too — not just a repeated accept.
    resp = client.post(f"/sacrifice/{proposal.id}/decline")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "sacrifice_already_resolved"


def test_sacrifice_requires_auth(client: TestClient, session: DbSession) -> None:
    assert client.post("/sacrifice/1/accept").status_code == 401
    assert client.post("/sacrifice/1/decline").status_code == 401


def test_unknown_proposal_is_404(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    login(client, "pasha")
    assert client.post("/sacrifice/9999/accept").status_code == 404


# --- audit trail (make audit.py truthful) -----------------------------------


def test_sacrifice_accept_and_solve_write_audit_rows(
    client: TestClient, session: DbSession
) -> None:
    """A solve and a sacrifice accept each leave an audit_log row (§5, §6). The
    audit docstring claims every sacrifice + solve transition is recorded."""
    roster = create_full_roster(session)
    monday = _future_monday()
    _week, proposal = _force_proposal(session, roster, monday, worker="pasha", day=Day.THU)

    solve_rows = session.scalars(select(AuditLog).where(AuditLog.action == "solve")).all()
    assert solve_rows, "the solve must be audited"

    login(client, "pasha")
    resp = client.post(f"/sacrifice/{proposal.id}/accept")
    assert resp.status_code == 200, resp.text

    rows = session.scalars(
        select(AuditLog).where(
            AuditLog.action == ACTION_SACRIFICE,
            AuditLog.entity_id == proposal.id,
        )
    ).all()
    transitions = {r.payload.get("transition") for r in rows if r.payload}
    assert "propose" in transitions  # the proposal being opened
    assert "accept" in transitions  # and the acceptance recorded


def test_decline_writes_a_decline_audit_row(client: TestClient, session: DbSession) -> None:
    """§5/§6: the decline half of the transition is audited too."""
    roster = create_full_roster(session)
    monday = _future_monday()
    _week, proposal = _force_proposal(session, roster, monday, worker="pasha", day=Day.THU)

    login(client, "pasha")
    assert client.post(f"/sacrifice/{proposal.id}/decline").status_code == 200

    rows = session.scalars(
        select(AuditLog).where(
            AuditLog.action == ACTION_SACRIFICE, AuditLog.entity_id == proposal.id
        )
    ).all()
    assert "decline" in {r.payload.get("transition") for r in rows if r.payload}


# --- re-solve guards while a §2.3 conversation is open -----------------------


def test_pending_proposal_blocks_resolve_no_duplicate(
    client: TestClient, session: DbSession
) -> None:
    """§2.3: while a PENDING proposal is open, a second /admin/solve is refused
    with 409 `sacrifice_pending` — the frozen constraints would only re-open a
    duplicate offer. No duplicate proposal and no duplicate sacrifice_proposed
    notice are created, and the week stays SOLVED."""
    roster = create_full_roster(session)
    monday = _future_monday()
    _force_proposal(session, roster, monday, worker="pasha", day=Day.THU)

    def counts() -> tuple[int, int]:
        session.expire_all()
        proposals = session.scalars(select(SacrificeProposal)).all()
        notes = session.scalars(
            select(Notification).where(Notification.event_type == EVENT_SACRIFICE_PROPOSED)
        ).all()
        return len(proposals), len(notes)

    assert counts() == (1, 1)  # one proposal, one worker notice

    login(client, "mattia")
    resp = _solve(client, monday)
    assert resp.status_code == 409
    assert resp.json()["detail"] == ERROR_SACRIFICE_PENDING

    assert counts() == (1, 1)  # blocked before run_solve: nothing duplicated
    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.SOLVED


def test_decline_then_resolve_does_not_re_offer_declined_worker(
    client: TestClient, session: DbSession
) -> None:
    """§2.3: a worker who declined is never re-offered by a later re-solve of the
    same (frozen) conflict. Pasha declines → DECLINED, week SOLVED, escalated. A
    fresh /admin/solve is allowed (SOLVED, no pending) and runs, but with Pasha
    excluded from the probe set: zero new PENDING proposals to him and no new
    sacrifice_proposed notice to him.
    """
    roster = create_full_roster(session)
    monday = _future_monday()
    week, proposal = _force_proposal(session, roster, monday, worker="pasha", day=Day.THU)

    login(client, "pasha")
    assert client.post(f"/sacrifice/{proposal.id}/decline").status_code == 200

    session.expire_all()
    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.SOLVED  # parked → re-solve allowed

    def pasha_proposed_notices() -> int:
        return len(
            session.scalars(
                select(Notification).where(
                    Notification.user_id == roster["pasha"].id,
                    Notification.event_type == EVENT_SACRIFICE_PROPOSED,
                )
            ).all()
        )

    before = pasha_proposed_notices()

    login(client, "mattia")
    resp = _solve(client, monday)
    assert resp.status_code == 200, resp.text  # SOLVED + no pending → guard lets it run

    session.expire_all()
    # Key invariant: no NEW pending proposal addressed to the declined worker...
    pasha_pending = session.scalars(
        select(SacrificeProposal).where(
            SacrificeProposal.user_id == roster["pasha"].id,
            SacrificeProposal.status == SacrificeStatus.PENDING,
        )
    ).all()
    assert pasha_pending == []
    # ...and no fresh sacrifice_proposed notice to him.
    assert pasha_proposed_notices() == before
    # His declined row is left as the record of the refusal, not rewritten.
    declined = session.scalars(
        select(SacrificeProposal).where(SacrificeProposal.status == SacrificeStatus.DECLINED)
    ).all()
    assert [p.user_id for p in declined] == [roster["pasha"].id]
