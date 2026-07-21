"""Schedule read + visibility (spec §7 `GET /schedule`, §3.3, §5 root rule).

The schedule "becomes visible to all" only when the week is locked (§3.3): a
worker sees nothing for an unpublished week, an admin previews it. The response
names workers — root (Matteo) included, since he works — but must never serialize
`is_root` (§5).
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DbSession

from app.enums import WeekStatus
from app.scheduling import get_or_create_week
from app.solve_service import run_solve
from tests.factories import PASSWORD, create_full_roster

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase3


def _future_monday(weeks_ahead: int = 2) -> dt.date:
    today = dt.datetime.now(dt.UTC).date()
    next_monday = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)
    return next_monday + dt.timedelta(weeks=weeks_ahead - 1)


def login(client: TestClient, username: str) -> None:
    resp = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _solve_and_lock(session: DbSession, monday: dt.date) -> None:
    """Simulate the lifecycle up to publish: solve, then lock the week (the
    dedicated publish step lands in the next increment)."""
    week = get_or_create_week(session, monday)
    run_solve(session, week)
    week.status = WeekStatus.LOCKED
    session.commit()


def test_schedule_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/schedule", params={"week": _future_monday().isoformat()})
    assert resp.status_code == 401


def test_worker_sees_locked_schedule(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    monday = _future_monday()
    _solve_and_lock(session, monday)

    login(client, "pasha")
    resp = client.get("/api/schedule", params={"week": monday.isoformat()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "locked"
    assert len(body["assignments"]) > 0


def test_worker_cannot_see_unpublished_schedule(client: TestClient, session: DbSession) -> None:
    """Solved but not locked: a worker gets an empty schedule, not the draft (§3.3)."""
    create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    run_solve(session, week)  # solved, still open (not published)

    login(client, "pasha")
    body = client.get("/api/schedule", params={"week": monday.isoformat()}).json()
    assert body["assignments"] == []


def test_admin_previews_unpublished_schedule(client: TestClient, session: DbSession) -> None:
    """Admin may preview the solved-but-unpublished grid (§3.2)."""
    create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    run_solve(session, week)

    login(client, "mattia")
    body = client.get("/api/schedule", params={"week": monday.isoformat()}).json()
    assert len(body["assignments"]) > 0


def test_schedule_never_serializes_is_root(client: TestClient, session: DbSession) -> None:
    """§5: root's shifts appear (Matteo works bagnino), but `is_root` never does."""
    create_full_roster(session)
    monday = _future_monday()
    _solve_and_lock(session, monday)

    login(client, "pasha")
    body = client.get("/api/schedule", params={"week": monday.isoformat()}).json()
    for a in body["assignments"]:
        assert "is_root" not in a
    # Matteo (root) is a working bagnino → he appears in the coverage.
    assert any(a["user_name"] == "Matteo" for a in body["assignments"])


def test_unknown_week_is_empty(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    login(client, "pasha")
    body = client.get("/api/schedule", params={"week": _future_monday(9).isoformat()}).json()
    assert body["assignments"] == []
    assert body["status"] == "open"
