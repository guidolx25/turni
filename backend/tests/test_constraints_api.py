"""Constraint CRUD over HTTP (spec §3.1, §7 `/constraints`, `/weeks`).

Exercises the lifecycle rules a route-level test is the right layer for: the
full_day ↔ am/pm exclusion, multi-week submission, the "editable only while open"
guard (closed-by-deadline and locked-by-status), and ownership (no cross-user
reads or deletes, §5 row 1).

Week dates are computed relative to `utcnow()` so an open week stays open however
long from now the suite runs; the closed-week cases use a fixed far-past Monday.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DbSession

from app.enums import WeekStatus
from app.models import Constraint, Week
from tests.factories import PASSWORD, create_user


def _future_monday(weeks_ahead: int = 2) -> dt.date:
    """A Monday whose Sunday-17:00 deadline is comfortably in the future (≥ 7 days
    out), so the submission window is open no matter when the test runs."""
    today = dt.datetime.now(dt.UTC).date()
    next_monday = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)
    return next_monday + dt.timedelta(weeks=weeks_ahead - 1)


_PAST_MONDAY = dt.date(2020, 1, 6)  # deadline 2020-01-05 17:00 — long closed.


def login(client: TestClient, username: str) -> None:
    resp = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _post(client: TestClient, monday: dt.date, **body: object):
    payload = {"week": monday.isoformat(), "day": "mon", "slot": "am", "kind": "hard"}
    payload.update(body)
    return client.post("/constraints", json=payload)


# --- auth ------------------------------------------------------------------


def test_constraints_require_auth(client: TestClient) -> None:
    assert (
        client.get("/constraints", params={"week": _future_monday().isoformat()}).status_code == 401
    )
    assert _post(client, _future_monday()).status_code == 401


# --- create + read ---------------------------------------------------------


def test_post_then_get_round_trips(client: TestClient, session: DbSession) -> None:
    create_user(session, "pasha")
    login(client, "pasha")
    monday = _future_monday()

    resp = _post(client, monday, day="tue", slot="pm", kind="soft", note="dentist")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["week"] == monday.isoformat()
    assert (body["day"], body["slot"], body["kind"], body["note"]) == (
        "tue",
        "pm",
        "soft",
        "dentist",
    )
    assert "is_root" not in body

    got = client.get("/constraints", params={"week": monday.isoformat()})
    assert got.status_code == 200
    assert [(c["day"], c["slot"]) for c in got.json()] == [("tue", "pm")]


def test_upsert_updates_in_place_no_duplicate(client: TestClient, session: DbSession) -> None:
    """§3.1 upsert on (user, week, day, slot): re-posting the same slot updates it
    rather than creating a second row."""
    create_user(session, "pasha")
    login(client, "pasha")
    monday = _future_monday()

    first = _post(client, monday, day="mon", slot="am", kind="hard")
    second = _post(client, monday, day="mon", slot="am", kind="soft", note="changed")
    assert first.json()["id"] == second.json()["id"]  # same row
    assert second.json()["kind"] == "soft"

    rows = client.get("/constraints", params={"week": monday.isoformat()}).json()
    assert len(rows) == 1


# --- full_day <-> am/pm exclusion (§3.1) -----------------------------------


def test_full_day_supersedes_am_and_pm(client: TestClient, session: DbSession) -> None:
    create_user(session, "pasha")
    login(client, "pasha")
    monday = _future_monday()

    _post(client, monday, day="wed", slot="am", kind="hard")
    _post(client, monday, day="wed", slot="pm", kind="hard")
    _post(client, monday, day="wed", slot="full_day", kind="hard")

    rows = client.get("/constraints", params={"week": monday.isoformat()}).json()
    wed = [c for c in rows if c["day"] == "wed"]
    assert [c["slot"] for c in wed] == ["full_day"]  # am + pm cleared


def test_am_supersedes_full_day(client: TestClient, session: DbSession) -> None:
    create_user(session, "pasha")
    login(client, "pasha")
    monday = _future_monday()

    _post(client, monday, day="thu", slot="full_day", kind="hard")
    _post(client, monday, day="thu", slot="am", kind="hard")

    rows = client.get("/constraints", params={"week": monday.isoformat()}).json()
    thu = [c for c in rows if c["day"] == "thu"]
    assert [c["slot"] for c in thu] == ["am"]  # full_day cleared


# --- multi-week ------------------------------------------------------------


def test_multi_week_submission_is_isolated(client: TestClient, session: DbSession) -> None:
    """§3: any future week may be submitted; each week's constraints are its own."""
    create_user(session, "pasha")
    login(client, "pasha")
    wk1, wk2 = _future_monday(2), _future_monday(3)

    _post(client, wk1, day="mon", slot="am")
    _post(client, wk2, day="fri", slot="pm")

    r1 = client.get("/constraints", params={"week": wk1.isoformat()}).json()
    r2 = client.get("/constraints", params={"week": wk2.isoformat()}).json()
    assert [(c["day"], c["slot"]) for c in r1] == [("mon", "am")]
    assert [(c["day"], c["slot"]) for c in r2] == [("fri", "pm")]


# --- editable only while open (§3.1) ---------------------------------------


def test_closed_window_rejected_and_no_week_created(client: TestClient, session: DbSession) -> None:
    """A past-deadline week is refused (409) and must not materialise a row."""
    create_user(session, "pasha")
    login(client, "pasha")

    resp = _post(client, _PAST_MONDAY)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "week_closed"
    assert session.query(Week).filter(Week.monday_date == _PAST_MONDAY).one_or_none() is None


def test_locked_week_rejects_submission(client: TestClient, session: DbSession) -> None:
    """A future week already locked (published) refuses new constraints (§3.3)."""
    create_user(session, "pasha")
    login(client, "pasha")
    monday = _future_monday()
    session.add(Week(monday_date=monday, status=WeekStatus.LOCKED))
    session.commit()

    resp = _post(client, monday)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "week_closed"


def test_non_monday_week_rejected(client: TestClient, session: DbSession) -> None:
    create_user(session, "pasha")
    login(client, "pasha")
    tuesday = _future_monday() + dt.timedelta(days=1)
    resp = _post(client, tuesday)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "week_not_monday"


# --- delete + ownership (§5 row 1) -----------------------------------------


def test_delete_own_constraint(client: TestClient, session: DbSession) -> None:
    create_user(session, "pasha")
    login(client, "pasha")
    monday = _future_monday()
    cid = _post(client, monday, day="mon", slot="am").json()["id"]

    assert client.delete(f"/constraints/{cid}").status_code == 204
    assert client.get("/constraints", params={"week": monday.isoformat()}).json() == []


def test_cannot_delete_another_users_constraint(client: TestClient, session: DbSession) -> None:
    """Ownership: deleting someone else's row 404s (no cross-user existence leak)."""
    owner = create_user(session, "pasha")
    create_user(session, "amir")
    monday = _future_monday()
    # Owner's constraint, inserted directly for this week.
    week = Week(monday_date=monday, status=WeekStatus.OPEN)
    session.add(week)
    session.commit()
    row = Constraint(user_id=owner.id, week_id=week.id, day="mon", slot="am", kind="hard")
    session.add(row)
    session.commit()

    login(client, "amir")
    resp = client.delete(f"/constraints/{row.id}")
    assert resp.status_code == 404
    # Still present for the owner.
    assert session.get(Constraint, row.id) is not None


def test_delete_missing_constraint_is_404(client: TestClient, session: DbSession) -> None:
    create_user(session, "pasha")
    login(client, "pasha")
    assert client.delete("/constraints/9999").status_code == 404


# --- /weeks ----------------------------------------------------------------


def test_weeks_lists_deadline_and_status(client: TestClient, session: DbSession) -> None:
    create_user(session, "pasha")
    login(client, "pasha")
    monday = _future_monday()
    _post(client, monday, day="mon", slot="am")  # materialises the week

    weeks = client.get("/weeks").json()
    assert len(weeks) == 1
    (wk,) = weeks
    assert wk["monday_date"] == monday.isoformat()
    assert wk["status"] == "open"
    assert wk["submission_deadline"] is not None
    assert wk["solved_at"] is None and wk["locked_at"] is None


def test_weeks_requires_auth(client: TestClient) -> None:
    assert client.get("/weeks").status_code == 401
