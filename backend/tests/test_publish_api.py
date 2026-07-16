"""Publish + lock + fan-out (spec §3.3, §7 `/admin/publish`, §8 solver_state, §10).

Publishing a solved week locks it, discharges the Phase 2 carry-forward by writing
each worker's `solver_state` from the H5 template, fans out `schedule_published`,
and audits. An unsolved (or INFEASIBLE) week cannot publish. Admin-only (§5).
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.enums import AssignmentSlot, ConstraintKind, ConstraintSlot, Day, WeekStatus
from app.models import AuditLog, Constraint, Notification, SolverState, Week
from app.notifications import EVENT_SCHEDULE_PUBLISHED
from app.scheduling import get_or_create_week
from app.solve_service import run_solve
from tests.factories import PASSWORD, create_full_roster


def _future_monday(weeks_ahead: int = 2) -> dt.date:
    today = dt.datetime.now(dt.UTC).date()
    next_monday = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)
    return next_monday + dt.timedelta(weeks=weeks_ahead - 1)


def login(client: TestClient, username: str) -> None:
    resp = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _solve(session: DbSession, monday: dt.date) -> None:
    run_solve(session, get_or_create_week(session, monday))


# --- authorization ----------------------------------------------------------


def test_publish_requires_admin(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    monday = _future_monday()
    _solve(session, monday)
    login(client, "pasha")
    assert client.post("/admin/publish", params={"week": monday.isoformat()}).status_code == 403


# --- happy path -------------------------------------------------------------


def test_publish_locks_the_week(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    monday = _future_monday()
    _solve(session, monday)
    login(client, "mattia")

    resp = client.post("/admin/publish", params={"week": monday.isoformat()})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "locked"

    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.LOCKED and week.locked_at is not None


def test_publish_writes_solver_state_from_template(client: TestClient, session: DbSession) -> None:
    """§8 carry-forward: after publish each core worker's Sunday boundary is stored
    (Matteo PM, Francesco AM, the two spiaggini NULL = FULL_DAY); the jolly has no
    row (absent from the Sunday template)."""
    roster = create_full_roster(session)
    monday = _future_monday()
    _solve(session, monday)
    login(client, "mattia")
    client.post("/admin/publish", params={"week": monday.isoformat()})

    state = {s.user_id: s for s in session.scalars(select(SolverState)).all()}
    assert state[roster["matteo"].id].last_worked_slot is AssignmentSlot.PM
    assert state[roster["francesco"].id].last_worked_slot is AssignmentSlot.AM
    assert state[roster["pasha"].id].last_worked_slot is None  # FULL_DAY
    assert state[roster["amir"].id].last_worked_slot is None
    assert roster["mattia"].id not in state  # jolly: no boundary term


def test_publish_fans_out_to_every_worker_including_root(
    client: TestClient, session: DbSession
) -> None:
    """§3.3/§10: every active worker gets a schedule_published notification — root
    (Matteo) included, since the shifts are his (a per-user broadcast, not a
    role-based fan-out §5 would hide him from)."""
    roster = create_full_roster(session)
    monday = _future_monday()
    _solve(session, monday)
    login(client, "mattia")
    client.post("/admin/publish", params={"week": monday.isoformat()})

    notes = session.scalars(select(Notification)).all()
    recipients = {n.user_id for n in notes}
    assert recipients == {u.id for u in roster.values()}  # all 5, incl root
    assert all(n.event_type == EVENT_SCHEDULE_PUBLISHED for n in notes)


def test_publish_records_audit(client: TestClient, session: DbSession) -> None:
    roster = create_full_roster(session)
    monday = _future_monday()
    _solve(session, monday)
    login(client, "mattia")
    client.post("/admin/publish", params={"week": monday.isoformat()})

    rows = session.scalars(select(AuditLog).where(AuditLog.action == "publish")).all()
    assert len(rows) == 1
    assert rows[0].entity == "week"
    assert rows[0].actor_id == roster["mattia"].id  # the admin who published


# --- guards -----------------------------------------------------------------


def test_publish_unsolved_week_is_409(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    monday = _future_monday()
    get_or_create_week(session, monday)  # exists, but never solved
    login(client, "mattia")

    resp = client.post("/admin/publish", params={"week": monday.isoformat()})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "week_not_solved"


def test_publish_unknown_week_is_404(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    login(client, "mattia")
    resp = client.post("/admin/publish", params={"week": _future_monday().isoformat()})
    assert resp.status_code == 404


def test_publish_twice_is_409(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    monday = _future_monday()
    _solve(session, monday)
    login(client, "mattia")
    client.post("/admin/publish", params={"week": monday.isoformat()})

    resp = client.post("/admin/publish", params={"week": monday.isoformat()})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "week_already_locked"


def test_infeasible_week_cannot_publish(client: TestClient, session: DbSession) -> None:
    """An INFEASIBLE solve stamps solved_at but leaves no assignments; publishing
    an empty schedule is refused (§3.3 needs a feasible schedule to lock)."""
    roster = create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    for name in ("matteo", "francesco", "mattia"):
        session.add(
            Constraint(
                user_id=roster[name].id,
                week_id=week.id,
                day=Day.MON,
                slot=ConstraintSlot.FULL_DAY,
                kind=ConstraintKind.HARD,
            )
        )
    session.commit()
    run_solve(session, week)  # infeasible

    login(client, "mattia")
    resp = client.post("/admin/publish", params={"week": monday.isoformat()})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "week_not_solved"


def test_worker_sees_schedule_after_publish(client: TestClient, session: DbSession) -> None:
    """End-to-end: once published, an ordinary worker can read the locked grid."""
    create_full_roster(session)
    monday = _future_monday()
    _solve(session, monday)
    login(client, "mattia")
    client.post("/admin/publish", params={"week": monday.isoformat()})

    # A different, non-admin worker now sees it.
    login(client, "pasha")
    body = client.get("/schedule", params={"week": monday.isoformat()}).json()
    assert body["status"] == "locked"
    assert len(body["assignments"]) > 0
