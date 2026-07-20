"""Solve orchestration + persistence (spec §3.2, §7 `/admin/solve`, §8 adapter).

Covers the DB ↔ solver adapter and its endpoint: a feasible solve persists the
weekday (solver) rows plus the fixed weekend template and closes the window; a
regenerate is idempotent; an over-constrained week returns the blocking
constraints and persists nothing (feeding §2.3). Admin-only per §5.

Week dates are computed from `utcnow()` so the submission window is open whenever
the suite runs.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.enums import AssignmentSource, ConstraintKind, ConstraintSlot, Day, WeekStatus
from app.models import Assignment, AuditLog, Constraint, Notification, SacrificeProposal, Week
from app.publish_service import ERROR_ALREADY_LOCKED
from app.scheduling import get_or_create_week, is_submittable
from app.solve_service import run_solve
from tests.factories import PASSWORD, create_full_roster


def _future_monday(weeks_ahead: int = 2) -> dt.date:
    today = dt.datetime.now(dt.UTC).date()
    next_monday = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)
    return next_monday + dt.timedelta(weeks=weeks_ahead - 1)


def login(client: TestClient, username: str) -> None:
    resp = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


# --- adapter (service level) ------------------------------------------------


def test_run_solve_persists_weekday_and_weekend_rows(session: DbSession) -> None:
    """A feasible solve writes solver rows for Mon–Fri and the H5 template for
    Sat/Sun, and stamps solved_at (closing the window, §3.2)."""
    create_full_roster(session)
    week = get_or_create_week(session, _future_monday())

    result = run_solve(session, week)
    assert result.status.value in ("optimal", "feasible")

    rows = session.scalars(select(Assignment).where(Assignment.week_id == week.id)).all()
    sources = {a.source for a in rows}
    assert AssignmentSource.SOLVER in sources
    assert AssignmentSource.WEEKEND_TEMPLATE in sources

    # Weekday rows are solver-sourced; weekend rows are template-sourced.
    weekdays = {Day.MON, Day.TUE, Day.WED, Day.THU, Day.FRI}
    assert all(a.source is AssignmentSource.SOLVER for a in rows if a.day in weekdays)
    assert all(
        a.source is AssignmentSource.WEEKEND_TEMPLATE for a in rows if a.day in {Day.SAT, Day.SUN}
    )

    session.refresh(week)
    assert week.solved_at is not None
    assert is_submittable(week) is False  # window closed by the solve


def test_regenerate_is_idempotent(session: DbSession) -> None:
    """Re-solving replaces the generated rows rather than duplicating them (the
    UNIQUE(week,day,slot,role) would otherwise blow up)."""
    create_full_roster(session)
    week = get_or_create_week(session, _future_monday())

    run_solve(session, week)
    first = session.scalars(select(Assignment).where(Assignment.week_id == week.id)).all()
    run_solve(session, week)
    second = session.scalars(select(Assignment).where(Assignment.week_id == week.id)).all()
    assert len(first) == len(second)


def test_infeasible_persists_nothing_and_names_blockers(session: DbSession) -> None:
    """All three bagnini blocked Monday → INFEASIBLE. No assignments persist, and
    the blocking constraints come back for the §2.3 sacrifice flow."""
    roster = create_full_roster(session)
    week = get_or_create_week(session, _future_monday())
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

    result = run_solve(session, week)
    assert result.status.value == "infeasible"
    assert session.scalars(select(Assignment).where(Assignment.week_id == week.id)).all() == []
    blockers = {(c.worker_id, c.day) for c in result.blocking_constraints}
    assert blockers  # non-empty attribution
    assert all(day is Day.MON for _, day in blockers)


# --- endpoint (§7 /admin/solve, §5 admin-only) ------------------------------


def test_admin_solve_requires_admin(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    login(client, "pasha")  # a plain worker
    resp = client.post("/admin/solve", params={"week": _future_monday().isoformat()})
    assert resp.status_code == 403


def test_admin_solve_returns_objective_breakdown(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    login(client, "mattia")  # the visible admin
    resp = client.post("/admin/solve", params={"week": _future_monday().isoformat()})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] in ("optimal", "feasible")
    assert body["objective"]["weighted_total"] >= 0
    assert body["blocking_constraints"] == []


def test_admin_solve_by_root_is_allowed(client: TestClient, session: DbSession) -> None:
    """Root inherits admin (§5), so Matteo may trigger a solve."""
    create_full_roster(session)
    login(client, "matteo")
    resp = client.post("/admin/solve", params={"week": _future_monday().isoformat()})
    assert resp.status_code == 200


def test_admin_solve_rejects_non_monday(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    login(client, "mattia")
    tuesday = _future_monday() + dt.timedelta(days=1)
    resp = client.post("/admin/solve", params={"week": tuesday.isoformat()})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "week_not_monday"


def test_solve_closes_submission_window(client: TestClient, session: DbSession) -> None:
    """After a solve, the week no longer accepts constraint edits (§3.2)."""
    create_full_roster(session)
    monday = _future_monday()
    login(client, "mattia")
    client.post("/admin/solve", params={"week": monday.isoformat()})

    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and is_submittable(week) is False


def test_early_solve_closes_window_for_post_and_delete_over_http(
    client: TestClient, session: DbSession
) -> None:
    """§3.2 "Generate now marks the window closed early": an early manual solve
    moves the week OPEN→`status=SOLVED` with `solved_at` set. POST /constraints and
    DELETE must AGREE — both 409 — so a solved schedule cannot be mutated by a
    late edit (the hazard: a pending sacrifice was probed against this very set).
    """
    create_full_roster(session)
    monday = _future_monday()

    # A worker submits while the window is genuinely open (well before Sun 17:00).
    login(client, "pasha")
    created = client.post(
        "/constraints",
        json={"week": monday.isoformat(), "day": "wed", "slot": "am", "kind": "soft"},
    )
    assert created.status_code == 201, created.text
    constraint_id = created.json()["id"]

    # Admin "Generate now" ahead of the natural deadline: stamps solved_at, SOLVED.
    login(client, "mattia")
    assert client.post("/admin/solve", params={"week": monday.isoformat()}).status_code == 200
    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.SOLVED and week.solved_at is not None

    # POST and DELETE now agree: both refuse the closed window.
    login(client, "pasha")
    post_after = client.post(
        "/constraints",
        json={"week": monday.isoformat(), "day": "thu", "slot": "pm", "kind": "soft"},
    )
    assert post_after.status_code == 409
    assert post_after.json()["detail"] == "week_closed"

    delete_after = client.delete(f"/constraints/{constraint_id}")
    assert delete_after.status_code == 409
    assert delete_after.json()["detail"] == "week_closed"


def test_admin_solve_writes_an_audit_row(client: TestClient, session: DbSession) -> None:
    """§5/§6: a solve is an audited transition; the actor is the triggering admin."""
    create_full_roster(session)
    monday = _future_monday()
    login(client, "mattia")
    assert client.post("/admin/solve", params={"week": monday.isoformat()}).status_code == 200

    week = session.scalar(select(Week).where(Week.monday_date == monday))
    rows = session.scalars(
        select(AuditLog).where(AuditLog.action == "solve", AuditLog.entity_id == week.id)
    ).all()
    assert rows, "the solve must write an audit_log row"
    assert rows[0].actor_id is not None  # the admin who triggered it


def test_manual_feasible_solve_parks_in_solved_invisible_no_fanout(
    client: TestClient, session: DbSession
) -> None:
    """§3.2/§3.3: a feasible manual "Generate now" leaves the week in `solved` —
    NOT `locked`. Visibility and fan-out key off `locked`, never `solved`: a plain
    worker still sees an empty schedule, an admin previews the solved grid, and no
    `schedule_published` notification has fired yet (that awaits an explicit publish).
    """
    create_full_roster(session)
    monday = _future_monday()

    login(client, "mattia")
    resp = client.post("/admin/solve", params={"week": monday.isoformat()})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] in ("optimal", "feasible")

    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.SOLVED

    # The worker sees nothing yet — the draft is not leaked before publish.
    login(client, "pasha")
    worker_grid = client.get("/schedule", params={"week": monday.isoformat()}).json()
    assert worker_grid["status"] == "solved"
    assert worker_grid["assignments"] == []

    # The admin may preview the solved grid.
    login(client, "mattia")
    admin_grid = client.get("/schedule", params={"week": monday.isoformat()}).json()
    assert admin_grid["assignments"], "admin previews the solved schedule"

    # No publish fan-out: `solved` never triggers §10 notifications.
    published = session.scalars(
        select(Notification).where(Notification.event_type == "schedule_published")
    ).all()
    assert published == []


# --- re-solve guards on the resolved week (§3.4 lock, §2.3 review phase) ------


def _generated_snapshot(session: DbSession, week_id: int) -> set:
    """The identifying tuple of every SOLVER/WEEKEND_TEMPLATE row for `week_id`.

    `id` is included so a delete+rewrite (which mints fresh autoincrement ids)
    is detectable, not just a change of holder — "byte-for-byte unchanged".
    """
    session.expire_all()
    rows = session.scalars(
        select(Assignment).where(
            Assignment.week_id == week_id,
            Assignment.source.in_((AssignmentSource.SOLVER, AssignmentSource.WEEKEND_TEMPLATE)),
        )
    ).all()
    return {(a.id, a.day, a.slot, a.role, a.user_id, a.source) for a in rows}


def test_locked_week_resolve_refused_preserves_published_rows(
    client: TestClient, session: DbSession
) -> None:
    """§3.4: a published (LOCKED) week refuses a re-solve with 409
    `week_already_locked`, and the published SOLVER + WEEKEND_TEMPLATE rows are
    left byte-for-byte — not deleted and rewritten under new ids."""
    create_full_roster(session)
    monday = _future_monday()
    login(client, "mattia")
    assert client.post("/admin/solve", params={"week": monday.isoformat()}).status_code == 200
    assert client.post("/admin/publish", params={"week": monday.isoformat()}).status_code == 200

    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.LOCKED
    before = _generated_snapshot(session, week.id)
    assert before  # the feasible publish left generated rows to preserve

    resp = client.post("/admin/solve", params={"week": monday.isoformat()})
    assert resp.status_code == 409
    assert resp.json()["detail"] == ERROR_ALREADY_LOCKED

    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.LOCKED  # still locked
    assert _generated_snapshot(session, week.id) == before  # ids + tuples identical


def test_feasible_solved_week_regenerate_still_allowed(
    client: TestClient, session: DbSession
) -> None:
    """§3.2: a feasible manual solve parks the week in SOLVED with no pending
    proposal; the review-phase regenerate must stay allowed — a second
    /admin/solve returns 200 and the week stays SOLVED (the lock/pending guards
    do not over-fire on the legitimate case)."""
    create_full_roster(session)
    monday = _future_monday()
    login(client, "mattia")
    assert client.post("/admin/solve", params={"week": monday.isoformat()}).status_code == 200

    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.SOLVED
    assert session.scalars(select(SacrificeProposal)).all() == []  # no open conflict

    resp = client.post("/admin/solve", params={"week": monday.isoformat()})
    assert resp.status_code == 200, resp.text

    session.expire_all()
    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.SOLVED
