"""The §2.3 sacrifice flow end to end (§7 `/sacrifice/*`, §2.3, §10).

Canonical resolvable conflict: a core worker submits a HARD Friday-off request.
H4 forces Friday worked, so the plain solve is INFEASIBLE — but extending that
worker's free-day domain to Friday (the probe) resolves it, so a proposal is
opened. Accept → re-solve pinned → publish. An unresolvable conflict escalates to
the admin instead. Only the target worker may act on their proposal.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.audit import ACTION_SACRIFICE
from app.enums import ConstraintKind, ConstraintSlot, Day, SacrificeStatus, WeekStatus
from app.models import AuditLog, Constraint, Notification, SacrificeProposal, Week
from app.notifications import (
    EVENT_SACRIFICE_ESCALATED,
    EVENT_SACRIFICE_PROPOSED,
)
from app.scheduling import get_or_create_week
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


# --- proposal generation ----------------------------------------------------


def test_friday_off_conflict_opens_a_proposal(client: TestClient, session: DbSession) -> None:
    """Pasha hard-off Friday → INFEASIBLE → a proposal offering Pasha a Friday
    free day, and Pasha gets a sacrifice_proposed notification."""
    roster = create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    _hard(session, roster["pasha"].id, week, Day.FRI)

    login(client, "mattia")
    resp = _solve(client, monday)
    assert resp.json()["status"] == "infeasible"

    proposals = session.scalars(select(SacrificeProposal)).all()
    assert len(proposals) == 1
    p = proposals[0]
    assert p.user_id == roster["pasha"].id
    assert p.proposed_free_day is Day.FRI
    assert p.status is SacrificeStatus.PENDING

    notes = session.scalars(
        select(Notification).where(Notification.user_id == roster["pasha"].id)
    ).all()
    assert any(n.event_type == EVENT_SACRIFICE_PROPOSED for n in notes)
    assert any(n.payload and n.payload.get("proposal_id") == p.id for n in notes)


def test_accept_re_solves_pinned_and_publishes(client: TestClient, session: DbSession) -> None:
    roster = create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    _hard(session, roster["pasha"].id, week, Day.FRI)
    login(client, "mattia")
    _solve(client, monday)
    proposal = session.scalars(select(SacrificeProposal)).one()

    login(client, "pasha")
    resp = client.post(f"/sacrifice/{proposal.id}/accept")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "accepted"

    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.LOCKED  # published

    # Pasha's honored request: he works zero Friday slots (Friday is his free day).
    login(client, "pasha")
    grid = client.get("/schedule", params={"week": monday.isoformat()}).json()
    pasha_fri = [
        a for a in grid["assignments"] if a["user_id"] == roster["pasha"].id and a["day"] == "fri"
    ]
    assert pasha_fri == []


def test_decline_escalates_to_admin_without_publishing(
    client: TestClient, session: DbSession
) -> None:
    roster = create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    _hard(session, roster["pasha"].id, week, Day.FRI)
    login(client, "mattia")
    _solve(client, monday)
    proposal = session.scalars(select(SacrificeProposal)).one()

    login(client, "pasha")
    resp = client.post(f"/sacrifice/{proposal.id}/decline")
    assert resp.status_code == 200
    assert resp.json()["status"] == "declined"

    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.OPEN  # not published

    # Mattia (visible admin) is notified of the escalation WITH the conflict
    # explanation (§2.3); root is not.
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


# --- authorization + state --------------------------------------------------


def test_only_target_worker_may_act(client: TestClient, session: DbSession) -> None:
    roster = create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    _hard(session, roster["pasha"].id, week, Day.FRI)
    login(client, "mattia")
    _solve(client, monday)
    proposal = session.scalars(select(SacrificeProposal)).one()

    login(client, "amir")  # not the target
    assert client.post(f"/sacrifice/{proposal.id}/accept").status_code == 404
    assert client.post(f"/sacrifice/{proposal.id}/decline").status_code == 404


def test_cannot_resolve_twice(client: TestClient, session: DbSession) -> None:
    roster = create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    _hard(session, roster["pasha"].id, week, Day.FRI)
    login(client, "mattia")
    _solve(client, monday)
    proposal = session.scalars(select(SacrificeProposal)).one()

    login(client, "pasha")
    client.post(f"/sacrifice/{proposal.id}/accept")
    resp = client.post(f"/sacrifice/{proposal.id}/accept")
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
    week = get_or_create_week(session, monday)
    _hard(session, roster["pasha"].id, week, Day.FRI)

    login(client, "mattia")
    _solve(client, monday)  # writes a solve row + a sacrifice propose row

    solve_rows = session.scalars(select(AuditLog).where(AuditLog.action == "solve")).all()
    assert solve_rows, "the solve must be audited"

    proposal = session.scalars(select(SacrificeProposal)).one()
    login(client, "pasha")
    resp = client.post(f"/sacrifice/{proposal.id}/accept")
    assert resp.status_code == 200, resp.text

    accept_rows = session.scalars(
        select(AuditLog).where(
            AuditLog.action == ACTION_SACRIFICE,
            AuditLog.entity_id == proposal.id,
        )
    ).all()
    transitions = {r.payload.get("transition") for r in accept_rows if r.payload}
    assert "propose" in transitions  # proposal opened during the solve
    assert "accept" in transitions  # and the acceptance recorded
