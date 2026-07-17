"""Full simulated week (spec §12 Phase 3 gate) — submissions → publish, through
one forced infeasibility → sacrifice → accept → re-solve.

This is the headline gate scenario, driven end-to-end through the HTTP API the
way the real lifecycle runs: workers submit constraints, an admin solves, the
resulting infeasibility opens a §2.3 proposal, the affected worker accepts via the
notification they received, the week re-solves and publishes, and every worker can
then read the locked schedule. The solver's own correctness has unit coverage; here
the point is that the *lifecycle wiring* holds together.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.enums import WeekStatus
from app.models import AuditLog, SolverState, Week
from tests.factories import PASSWORD, create_full_roster


def _future_monday(weeks_ahead: int = 2) -> dt.date:
    today = dt.datetime.now(dt.UTC).date()
    next_monday = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)
    return next_monday + dt.timedelta(weeks=weeks_ahead - 1)


def login(client: TestClient, username: str) -> None:
    resp = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _submit(client: TestClient, monday: dt.date, day: str, slot: str, kind: str) -> None:
    resp = client.post(
        "/constraints",
        json={"week": monday.isoformat(), "day": day, "slot": slot, "kind": kind},
    )
    assert resp.status_code == 201, resp.text


def test_full_week_submissions_to_publish_via_sacrifice(
    client: TestClient, session: DbSession
) -> None:
    roster = create_full_roster(session)
    monday = _future_monday()

    # 1) Workers submit their week's constraints (soft preferences + one hard
    #    Friday-off that no standard schedule can honor).
    login(client, "francesco")
    _submit(client, monday, "tue", "full_day", "soft")  # prefers Tuesday off
    login(client, "amir")
    _submit(client, monday, "wed", "full_day", "soft")  # prefers Wednesday off
    login(client, "pasha")
    _submit(client, monday, "mon", "full_day", "soft")  # prefers Monday off
    _submit(client, monday, "fri", "full_day", "hard")  # HARD Friday off → infeasible

    # The week is now materialised, open, with submissions visible to their owner.
    weeks = client.get("/weeks").json()
    assert any(w["monday_date"] == monday.isoformat() and w["status"] == "open" for w in weeks)
    assert len(client.get("/constraints", params={"week": monday.isoformat()}).json()) == 2

    # 2) Admin closes the window and solves → INFEASIBLE (Friday can't be off).
    login(client, "mattia")
    solve = client.post("/admin/solve", params={"week": monday.isoformat()})
    assert solve.status_code == 200
    assert solve.json()["status"] == "infeasible"

    # 3) The §2.3 proposal reached Pasha; he reads it off his notifications.
    login(client, "pasha")
    notes = client.get("/notifications").json()
    proposed = next(n for n in notes if n["event_type"] == "sacrifice_proposed")
    assert proposed["payload"]["proposed_free_day"] == "fri"
    proposal_id = proposed["payload"]["proposal_id"]

    # 4) Pasha accepts → re-solve with Friday pinned free → auto-publish.
    accept = client.post(f"/sacrifice/{proposal_id}/accept")
    assert accept.status_code == 200
    assert accept.json()["status"] == "accepted"

    # 5) The week is published (locked) and every worker was notified.
    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.LOCKED
    login(client, "amir")  # an uninvolved worker
    assert any(n["event_type"] == "schedule_published" for n in client.get("/notifications").json())

    # 6) The published schedule is visible to all and is well-formed.
    grid = client.get("/schedule", params={"week": monday.isoformat()}).json()
    assert grid["status"] == "locked"
    _assert_h1_weekday_coverage(grid["assignments"])
    # Pasha's honored hard request: zero Friday slots.
    assert not [
        a for a in grid["assignments"] if a["user_id"] == roster["pasha"].id and a["day"] == "fri"
    ]

    # 7) Post-publish invariants: window closed, solver_state seeded, publish audited.
    login(client, "pasha")
    assert (
        client.post(
            "/constraints",
            json={"week": monday.isoformat(), "day": "mon", "slot": "am", "kind": "hard"},
        ).status_code
        == 409  # week_closed
    )
    assert session.scalars(select(SolverState)).all()  # next-week boundary written
    assert session.scalars(select(AuditLog).where(AuditLog.action == "publish")).all()


def _assert_h1_weekday_coverage(assignments: list[dict]) -> None:
    """H1: every Mon–Fri slot has exactly one bagnino and exactly one spiaggino."""
    for day in ("mon", "tue", "wed", "thu", "fri"):
        for slot in ("am", "pm"):
            holders = [a for a in assignments if a["day"] == day and a["slot"] == slot]
            roles = sorted(a["role"] for a in holders)
            assert roles == ["bagnino", "spiaggino"], f"{day}/{slot}: {roles}"
