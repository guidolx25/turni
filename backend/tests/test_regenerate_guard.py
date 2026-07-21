"""The regenerate-vs-post-lock-rows guard (spec §3.2/§3.4, §6, §4, §5).

A carry-forward, pinned rather than fixed — because what makes it safe is a
refusal, and a refusal is exactly the kind of thing a later change removes
without noticing.

`solve_service._clear_generated_assignments` deletes only `solver` and
`weekend_template` rows: §4 and §5 rows are authored elsewhere and must survive a
regenerate. But an applied swap or an override RESTAMPS an existing row's source
to `swap`/`override`, so such a row survives the clear while the solver writes a
fresh row for the same `(week, day, slot, role)` — which the §6 partial unique
index forbids on Mon–Fri. The result would be an IntegrityError at best.

It is unreachable today for one reason only: a swap or an override requires a
LOCKED week (§3.4), and `POST /admin/solve` refuses a LOCKED week (§3.2 — post-lock
changes are swaps or override, never a re-solve that would clobber published
rows). These tests pin that refusal from both ends, so any future regenerate path
has to confront the collision deliberately.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.enums import AssignmentRole, AssignmentSlot, AssignmentSource, Day, WeekStatus
from app.models import Assignment, User, Week
from app.publish_service import ERROR_ALREADY_LOCKED, publish_week
from app.scheduling import get_or_create_week
from app.solve_service import run_solve
from app.solver import SOLVER_DAYS
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


def _published_week(session: DbSession, roster: dict[str, User], monday: dt.date) -> Week:
    week = get_or_create_week(session, monday)
    assert run_solve(session, week).status.value in ("optimal", "feasible")
    publish_week(session, week, roster["mattia"])
    session.commit()
    session.refresh(week)
    return week


def test_a_locked_week_with_override_rows_refuses_to_regenerate(
    client: TestClient, session: DbSession
) -> None:
    """The exact collision scenario, proven unreachable.

    An override restamps a Mon–Fri row `source=override`. A regenerate would keep
    that row (it is not the solver's to delete) and write a fresh `solver` row for
    the same `(week, day, slot, role)` — which the §6 partial unique index
    forbids. `/admin/solve` refuses the LOCKED week first, so the two never meet.
    """
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    row = next(
        a
        for a in session.scalars(select(Assignment).where(Assignment.week_id == week.id)).all()
        if a.day in SOLVER_DAYS and a.role is AssignmentRole.BAGNINO
    )
    login(client, "mattia")
    assert (
        client.post(
            "/api/admin/override",
            json={
                "week": week.monday_date.isoformat(),
                "day": row.day.value,
                "slot": row.slot.value,
                "role": row.role.value,
                "user_id": roster["mattia"].id,
            },
        ).status_code
        == 200
    )

    resp = client.post("/api/admin/solve", params={"week": week.monday_date.isoformat()})
    assert resp.status_code == 409, "§3.4: a published week is never re-solved"
    assert resp.json()["detail"] == ERROR_ALREADY_LOCKED

    # And the override row is still standing, unduplicated.
    session.expire_all()
    same_slot = session.scalars(
        select(Assignment).where(
            Assignment.week_id == week.id,
            Assignment.day == row.day,
            Assignment.slot == row.slot,
            Assignment.role == row.role,
        )
    ).all()
    assert len(same_slot) == 1
    assert same_slot[0].source is AssignmentSource.OVERRIDE


def test_post_lock_rows_can_only_exist_on_a_locked_week(
    client: TestClient, session: DbSession
) -> None:
    """The other end of the argument: `swap`/`override` rows are created ONLY by
    instruments that require a LOCKED week (§3.4), which is why an unlocked week —
    the only kind `/admin/solve` will regenerate — can never contain one."""
    roster = create_full_roster(session)
    week = get_or_create_week(session, _future_monday())
    run_solve(session, week)
    session.commit()
    assert week.status is WeekStatus.SOLVED

    login(client, "mattia")
    refused = client.post(
        "/api/admin/override",
        json={
            "week": week.monday_date.isoformat(),
            "day": Day.MON.value,
            "slot": AssignmentSlot.AM.value,
            "role": AssignmentRole.BAGNINO.value,
            "user_id": roster["mattia"].id,
        },
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "week_not_locked"

    # So a regenerate of this week sees only rows it owns, and succeeds.
    again = client.post("/api/admin/solve", params={"week": week.monday_date.isoformat()})
    assert again.status_code == 200, again.text
    sources = {
        a.source
        for a in session.scalars(select(Assignment).where(Assignment.week_id == week.id)).all()
    }
    assert sources <= {AssignmentSource.SOLVER, AssignmentSource.WEEKEND_TEMPLATE}
