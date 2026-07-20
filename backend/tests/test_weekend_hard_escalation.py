"""HARD requests on the H5 weekend template escalate, never resolve silently.

§2.1 H5 fixes Sat/Sun as a template: the solver builds no weekend variables, so a
HARD (H7) request on Sat/Sun has nothing to bind to and is skipped by the model.
Dropping it there and saying nothing would leave the worker believing an
unavailability is honored while the template schedules them anyway — the silent
resolution §2.3 forbids.

So the row is still accepted (201, §3.1 records a legitimate request) AND a human
is told: `constraints._escalate_weekend_hard` notifies the *visible* admins
(`weekend_hard_escalated`) and writes an `escalate` audit row.

The trigger is narrow, and each edge is pinned below:
  * kind=HARD and day ∈ {sat, sun} only — a SOFT weekend request and a HARD
    weekday request are both silent here;
  * only on the transition INTO hard, so re-upserting an already-HARD row does
    not re-notify, while a soft→hard flip does;
  * never on delete;
  * root is never a recipient of the role-based fan-out (§5);
  * with zero visible admins it logs an error rather than escalating into the void.
"""

from __future__ import annotations

import datetime as dt
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.audit import ACTION_ESCALATE
from app.constraints import upsert_constraint
from app.enums import ConstraintKind, ConstraintSlot, Day, UserRole
from app.models import AuditLog, Notification
from app.notifications import EVENT_WEEKEND_HARD_ESCALATED
from app.scheduling import get_or_create_week
from tests.factories import PASSWORD, create_full_roster, create_user

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase3


def _future_monday(weeks_ahead: int = 2) -> dt.date:
    today = dt.datetime.now(dt.UTC).date()
    next_monday = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)
    return next_monday + dt.timedelta(weeks=weeks_ahead - 1)


def login(client: TestClient, username: str) -> None:
    resp = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _submit(client: TestClient, monday: dt.date, day: str, slot: str, kind: str):
    return client.post(
        "/constraints",
        json={"week": monday.isoformat(), "day": day, "slot": slot, "kind": kind},
    )


def _escalate_audits(session: DbSession) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).where(AuditLog.action == ACTION_ESCALATE)).all())


def _escalations(session: DbSession) -> list[Notification]:
    return list(
        session.scalars(
            select(Notification).where(Notification.event_type == EVENT_WEEKEND_HARD_ESCALATED)
        ).all()
    )


# --- the escalation fires ---------------------------------------------------


@pytest.mark.parametrize("weekend_day", ["sat", "sun"])
def test_hard_weekend_request_is_accepted_and_escalated(
    client: TestClient, session: DbSession, weekend_day: str
) -> None:
    """§2.3/§H5: a HARD Sat or Sun request returns 201 (the request is recorded)
    and escalates to the visible admin, carrying enough context to reconcile it
    against the template by hand."""
    roster = create_full_roster(session)
    monday = _future_monday()

    login(client, "pasha")
    resp = _submit(client, monday, weekend_day, "full_day", "hard")
    assert resp.status_code == 201, resp.text
    constraint_id = resp.json()["id"]

    notes = _escalations(session)
    assert len(notes) == 1, "exactly one visible admin must be escalated to"
    note = notes[0]
    assert note.user_id == roster["mattia"].id  # the visible admin
    assert note.payload["day"] == weekend_day
    assert note.payload["slot"] == "full_day"
    assert note.payload["constraint_id"] == constraint_id
    assert note.payload["user_id"] == roster["pasha"].id
    assert note.payload["week"] == monday.isoformat()
    # §2.3: the escalation says WHY a human is needed, not merely that one is.
    assert note.payload["reason"] == "weekend_template_fixed"


def test_hard_weekend_request_never_notifies_root(client: TestClient, session: DbSession) -> None:
    """§5 (standing project rule): the escalation is a role-based fan-out, so the
    root account is never a recipient — even though root inherits admin capability.
    Matteo holds root; only Mattia, the visible admin, is notified."""
    roster = create_full_roster(session)
    monday = _future_monday()

    login(client, "pasha")
    assert _submit(client, monday, "sat", "full_day", "hard").status_code == 201

    recipients = {n.user_id for n in _escalations(session)}
    assert roster["matteo"].id not in recipients, "root must never receive a role-based fan-out"
    assert recipients == {roster["mattia"].id}


def test_hard_weekend_request_writes_an_escalate_audit_row(
    client: TestClient, session: DbSession
) -> None:
    """§5/§6: the escalation is an audited transition, attributed to the submitting
    worker and pointing at the constraint row."""
    roster = create_full_roster(session)
    monday = _future_monday()

    login(client, "pasha")
    resp = _submit(client, monday, "sun", "am", "hard")
    assert resp.status_code == 201, resp.text
    constraint_id = resp.json()["id"]

    rows = _escalate_audits(session)
    assert len(rows) == 1
    assert rows[0].entity == "constraint"
    assert rows[0].entity_id == constraint_id
    assert rows[0].actor_id == roster["pasha"].id
    assert rows[0].payload["day"] == "sun"


def test_soft_to_hard_flip_on_a_weekend_day_escalates(
    client: TestClient, session: DbSession
) -> None:
    """The trigger is the transition INTO hard: a row submitted SOFT is silent,
    and flipping it to HARD escalates exactly once."""
    create_full_roster(session)
    monday = _future_monday()

    login(client, "pasha")
    assert _submit(client, monday, "sat", "full_day", "soft").status_code == 201
    assert _escalations(session) == []  # soft is honored best-effort, no human needed

    assert _submit(client, monday, "sat", "full_day", "hard").status_code == 201
    assert len(_escalations(session)) == 1


# --- and does NOT fire otherwise --------------------------------------------


@pytest.mark.parametrize("weekend_day", ["sat", "sun"])
def test_soft_weekend_request_does_not_escalate(
    client: TestClient, session: DbSession, weekend_day: str
) -> None:
    """A SOFT weekend request is an S1 preference, not an unsatisfiable H7 demand:
    nothing is silently dropped, so no human is summoned."""
    create_full_roster(session)
    monday = _future_monday()

    login(client, "pasha")
    assert _submit(client, monday, weekend_day, "full_day", "soft").status_code == 201

    assert _escalations(session) == []
    assert _escalate_audits(session) == []


@pytest.mark.parametrize("weekday", ["mon", "tue", "wed", "thu", "fri"])
def test_hard_weekday_request_does_not_escalate(
    client: TestClient, session: DbSession, weekday: str
) -> None:
    """A HARD Mon–Fri request binds to real solver variables (H7 assumption
    literal), so it is resolved by the solver — not by the weekend escalation."""
    create_full_roster(session)
    monday = _future_monday()

    login(client, "pasha")
    assert _submit(client, monday, weekday, "full_day", "hard").status_code == 201

    assert _escalations(session) == []
    assert _escalate_audits(session) == []


def test_re_upsert_of_an_already_hard_weekend_row_does_not_re_notify(
    client: TestClient, session: DbSession
) -> None:
    """Editing an already-HARD weekend row (e.g. changing its note) is not a new
    request: the admin is escalated to once, not once per save."""
    create_full_roster(session)
    monday = _future_monday()

    login(client, "pasha")
    assert _submit(client, monday, "sat", "full_day", "hard").status_code == 201
    assert len(_escalations(session)) == 1

    for _ in range(3):
        resp = client.post(
            "/constraints",
            json={
                "week": monday.isoformat(),
                "day": "sat",
                "slot": "full_day",
                "kind": "hard",
                "note": "still unavailable",
            },
        )
        assert resp.status_code == 201, resp.text

    assert len(_escalations(session)) == 1, "an already-hard row must not re-notify"
    assert len(_escalate_audits(session)) == 1


def test_deleting_a_hard_weekend_row_does_not_escalate(
    client: TestClient, session: DbSession
) -> None:
    """Withdrawal is not a request: deleting the row escalates nothing further."""
    create_full_roster(session)
    monday = _future_monday()

    login(client, "pasha")
    created = _submit(client, monday, "sat", "full_day", "hard")
    assert created.status_code == 201
    before = len(_escalations(session))

    assert client.delete(f"/constraints/{created.json()['id']}").status_code == 204

    assert len(_escalations(session)) == before  # no new notification
    assert len(_escalate_audits(session)) == 1


# --- degenerate roster ------------------------------------------------------


def test_no_visible_admin_logs_an_error_instead_of_escalating_into_the_void(
    session: DbSession, caplog: pytest.LogCaptureFixture
) -> None:
    """§2.3: with no visible admin nobody can reconcile the request against the H5
    template. The row is still written, no notification is invented, and the gap is
    made loud in the log rather than passing silently.

    Driven through `upsert_constraint` rather than the HTTP route on purpose:
    `caplog` does not capture records emitted inside the TestClient's request
    thread, so an over-HTTP version of this assertion would pass vacuously. The
    escalation branch under test is route-independent.
    """
    # A roster whose only admin-capable account is root, which the fan-out excludes.
    create_user(session, "matteo", role=UserRole.BAGNINO, is_root=True)
    pasha = create_user(session, "pasha", role=UserRole.SPIAGGINO)
    week = get_or_create_week(session, _future_monday())

    with caplog.at_level(logging.ERROR, logger="app.constraints"):
        row = upsert_constraint(
            session,
            pasha,
            week,
            Day.SAT,
            ConstraintSlot.FULL_DAY,
            ConstraintKind.HARD,
            None,
        )
    assert row.id is not None  # the request is still recorded

    assert _escalations(session) == []  # nobody visible to notify
    errors = [rec for rec in caplog.records if rec.levelno == logging.ERROR]
    assert errors, "the unreachable escalation must be logged as an error"
    message = errors[0].getMessage().lower()
    assert "no visible admin" in message
    # The log must identify the orphaned request, not merely announce a gap.
    assert "pasha" in message and "sat" in message and str(row.id) in message
    # The audit row still lands: the escalation attempt is on the record.
    assert _escalate_audits(session)
