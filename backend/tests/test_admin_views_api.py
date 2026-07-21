"""The admin read surface (spec §7 `GET /admin/constraints`, `GET /admin/audit`).

§5 rows 5-6: "view all constraint submissions" and "view audit log", admin/root
only. Both are listings, so both carry the §5 root question — answered
differently, and deliberately:

* root's SUBMISSIONS appear, because §5 hides the root ROLE ("hidden from user
  lists, worker pickers, and notification recipients-by-role"), not the fact that
  Matteo is a working bagnino who submits constraints like anyone else;
* `is_root` itself is serialized nowhere, on any endpoint, ever.

The audit view additionally has to make §6's NULL `actor_id` legible: it means a
system action ("cron solve, 48 h swap expiry, nightly backup ... there is
deliberately no system user row"), never a user who vanished.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.enums import ConstraintKind, ConstraintSlot, Day
from app.models import Week
from app.scheduling import get_or_create_week
from app.solve_service import run_solve
from tests.factories import PASSWORD, create_full_roster

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase6


def _future_monday(weeks_ahead: int = 2) -> dt.date:
    today = dt.datetime.now(dt.UTC).date()
    next_monday = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)
    return next_monday + dt.timedelta(weeks=weeks_ahead - 1)


def login(client: TestClient, username: str) -> None:
    resp = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _submit(client: TestClient, week: dt.date, day: Day, slot: ConstraintSlot, kind: str) -> None:
    resp = client.post(
        "/api/constraints",
        json={
            "week": week.isoformat(),
            "day": day.value,
            "slot": slot.value,
            "kind": kind,
            "note": None,
        },
    )
    assert resp.status_code == 201, resp.text


# --- GET /admin/constraints --------------------------------------------------


def test_all_constraints_requires_the_admin_tier(client: TestClient, session: DbSession) -> None:
    """§5 row 5: a plain worker sees only their own (`GET /constraints`)."""
    create_full_roster(session)
    monday = _future_monday()
    get_or_create_week(session, monday)
    login(client, "pasha")
    resp = client.get("/api/admin/constraints", params={"week": monday.isoformat()})
    assert resp.status_code == 403


def test_all_constraints_returns_every_workers_submissions(
    client: TestClient, session: DbSession
) -> None:
    """§5 row 5: the admin sees the whole week's submissions, named."""
    roster = create_full_roster(session)
    monday = _future_monday()
    login(client, "pasha")
    _submit(client, monday, Day.MON, ConstraintSlot.AM, ConstraintKind.SOFT.value)
    login(client, "francesco")
    _submit(client, monday, Day.TUE, ConstraintSlot.FULL_DAY, ConstraintKind.HARD.value)

    login(client, "mattia")
    resp = client.get("/api/admin/constraints", params={"week": monday.isoformat()})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["week"] == monday.isoformat()
    assert body["status"] == "open"
    by_user = {c["user_id"]: c for c in body["constraints"]}
    assert set(by_user) == {roster["pasha"].id, roster["francesco"].id}
    assert by_user[roster["francesco"].id]["kind"] == "hard"
    assert by_user[roster["francesco"].id]["slot"] == "full_day"
    assert by_user[roster["pasha"].id]["user_name"] == roster["pasha"].display_name


def test_all_constraints_includes_roots_own_submissions(
    client: TestClient, session: DbSession
) -> None:
    """§5: root's ROLE is hidden, not his work. Matteo is a core bagnino whose
    availability the solver must honour (H7), so an admin planning the week has to
    see it — while `is_root` appears nowhere on the wire."""
    roster = create_full_roster(session)
    monday = _future_monday()
    login(client, "matteo")
    _submit(client, monday, Day.WED, ConstraintSlot.PM, ConstraintKind.HARD.value)

    login(client, "mattia")
    resp = client.get("/api/admin/constraints", params={"week": monday.isoformat()})
    assert resp.status_code == 200
    assert roster["matteo"].id in {c["user_id"] for c in resp.json()["constraints"]}
    assert "is_root" not in resp.text


def test_all_constraints_404s_an_unmaterialised_week(
    client: TestClient, session: DbSession
) -> None:
    """A GET must not create a week row as a side effect of being asked about one."""
    create_full_roster(session)
    login(client, "mattia")
    resp = client.get(
        "/api/admin/constraints", params={"week": _future_monday(weeks_ahead=9).isoformat()}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "week_not_found"
    assert session.scalars(select(Week)).all() == [], "the GET must not have minted a week"


# --- GET /admin/audit --------------------------------------------------------


def test_audit_requires_the_admin_tier(client: TestClient, session: DbSession) -> None:
    """§5 row 6: "view audit log" is admin/root only."""
    create_full_roster(session)
    login(client, "pasha")
    assert client.get("/api/admin/audit").status_code == 403


def test_root_inherits_the_audit_capability(client: TestClient, session: DbSession) -> None:
    """§5: root inherits every admin row — through `is_root`, not `is_admin`."""
    roster = create_full_roster(session)
    assert not roster["matteo"].is_admin
    login(client, "matteo")
    assert client.get("/api/admin/audit").status_code == 200


def test_audit_marks_a_null_actor_as_a_system_action(
    client: TestClient, session: DbSession
) -> None:
    """§6: "actor_id NULL means a system action (cron solve, 48 h swap expiry,
    nightly backup) ... there is deliberately no system user row."

    So the wire says `system: true` with a null actor, rather than emitting a
    nameless row the panel would have to interpret as a lookup failure — which §6
    is explicit it never is ("users are never hard-deleted, so a NULL actor_id is
    never a vanished human").
    """
    roster = create_full_roster(session)
    week = get_or_create_week(session, _future_monday())
    run_solve(session, week)  # actor=None — the cron path
    audit.record(session, roster["mattia"], audit.ACTION_PUBLISH, "week", week.id, None)
    session.commit()

    login(client, "mattia")
    body = client.get("/api/admin/audit").json()
    by_action = {e["action"]: e for e in body["entries"]}
    system_entry = by_action["solve"]
    assert system_entry["system"] is True
    assert system_entry["actor_id"] is None
    assert system_entry["actor_name"] is None
    human_entry = by_action["publish"]
    assert human_entry["system"] is False
    assert human_entry["actor_id"] == roster["mattia"].id
    assert human_entry["actor_name"] == roster["mattia"].display_name


def test_audit_is_newest_first_and_paginated(client: TestClient, session: DbSession) -> None:
    """Newest first, `limit`/`offset`, and a `total` that counts the matches
    rather than the page — otherwise a panel cannot page without probing."""
    create_full_roster(session)
    for index in range(5):
        audit.record(session, None, audit.ACTION_SOLVE, "week", index, {"n": index})
    session.commit()

    login(client, "mattia")
    first = client.get("/api/admin/audit", params={"limit": 2}).json()
    assert first["total"] == 5
    assert [e["entity_id"] for e in first["entries"]] == [4, 3]
    second = client.get("/api/admin/audit", params={"limit": 2, "offset": 2}).json()
    assert [e["entity_id"] for e in second["entries"]] == [2, 1]


def test_audit_filters_by_action_and_entity(client: TestClient, session: DbSession) -> None:
    """§5's audit view filters on the stable `app.audit` verb vocabulary."""
    create_full_roster(session)
    audit.record(session, None, audit.ACTION_SOLVE, "week", 1, None)
    audit.record(session, None, audit.ACTION_SWAP, "swap_request", 2, None)
    session.commit()

    login(client, "mattia")
    solves = client.get("/api/admin/audit", params={"action": "solve"}).json()
    assert solves["total"] == 1
    assert solves["entries"][0]["entity"] == "week"
    swaps = client.get("/api/admin/audit", params={"entity": "swap_request"}).json()
    assert swaps["total"] == 1
    assert swaps["entries"][0]["action"] == "swap"


def test_audit_limit_is_capped(client: TestClient, session: DbSession) -> None:
    """One request must not be able to ask for the whole history at once."""
    create_full_roster(session)
    login(client, "mattia")
    assert client.get("/api/admin/audit", params={"limit": 10_000}).status_code == 422
    assert client.get("/api/admin/audit", params={"limit": 0}).status_code == 422
    assert client.get("/api/admin/audit", params={"offset": -1}).status_code == 422


def test_audit_never_serializes_is_root(client: TestClient, session: DbSession) -> None:
    """§5: root may be an ACTOR (he publishes, he overrides) and his display name
    appears — which discloses a worker, not an authority. `is_root` does not."""
    roster = create_full_roster(session)
    audit.record(session, roster["matteo"], audit.ACTION_PUBLISH, "week", 1, None)
    session.commit()

    login(client, "mattia")
    resp = client.get("/api/admin/audit")
    assert resp.status_code == 200
    assert "is_root" not in resp.text
