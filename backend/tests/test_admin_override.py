"""Admin override of a locked slot (spec §5, §3.4, §7 `POST /admin/override`, §10).

The §12 Phase 6 gate names one criterion for this endpoint: "admin override on a
locked slot notifies affected workers". That is here, together with the two rules
that make an override safe rather than merely powerful:

* it may leave H2/H3/H4 violated — those bind the SOLVER (§2.1/§8), while §5
  grants the admin authority over the locked result — but it may never be silent,
  so the violations come back in the response and into the audit payload;
* §2.1 H5 names override alongside swap as the only two things that can move a
  WEEKEND row, and §2.2 seeds next Monday's alternation from the Sunday that
  actually happened. So an override touching Sunday must re-derive `solver_state`
  exactly as an accepted weekend swap does — the two tests at the bottom mirror
  `test_swaps_api.py`'s pair.

Rows are located by SHAPE, never by hardcoded id: each test states the schedule
feature it needs and fails loudly if the solver's output does not contain it.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.enums import (
    AssignmentRole,
    AssignmentSlot,
    AssignmentSource,
    Day,
    UserRole,
    WeekStatus,
)
from app.models import Assignment, AuditLog, Notification, SolverState, User, Week
from app.notifications import EVENT_ADMIN_OVERRIDE
from app.publish_service import publish_week
from app.scheduling import get_or_create_week
from app.solve_service import run_solve
from app.solver import SOLVER_DAYS
from tests.factories import PASSWORD, create_full_roster, create_user

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
    """A real LOCKED week: solve, then publish. Override is the post-lock
    instrument (§3.4), so every test here needs one."""
    week = get_or_create_week(session, monday)
    result = run_solve(session, week)
    assert result.status.value in ("optimal", "feasible"), "the fixture week must solve"
    publish_week(session, week, roster["mattia"])
    session.commit()
    session.refresh(week)
    assert week.status is WeekStatus.LOCKED
    return week


def _rows(session: DbSession, week: Week) -> list[Assignment]:
    return list(session.scalars(select(Assignment).where(Assignment.week_id == week.id)).all())


def _override(client: TestClient, week: Week, row: Assignment, user_id: int, **extra: Any):
    """POST the override that seats `user_id` in `row`'s slot, by natural key."""
    body: dict[str, Any] = {
        "week": week.monday_date.isoformat(),
        "day": row.day.value,
        "slot": row.slot.value,
        "role": row.role.value,
        "user_id": user_id,
    }
    body.update(extra)
    return client.post("/api/admin/override", json=body)


def _weekday_bagnino_pair(
    rows: list[Assignment], core_ids: set[int] | None = None
) -> tuple[Assignment, Assignment]:
    """A weekday whose AM and PM bagnino rows are held by two DIFFERENT people.

    With `core_ids`, both holders must be CORE workers — the scenario the H3/H4
    test needs: moving one onto the other's slot doubles that worker's day (H4)
    and leaves the displaced one with a second free weekday (H3). The jolly is
    exempt from both (H6), so a pair including him would prove nothing. Such a day
    always exists: on Friday no core worker is free (H3's default domain is
    Mon–Thu), so both core bagnini work it.
    """
    for day in SOLVER_DAYS:
        by_slot = {a.slot: a for a in rows if a.day is day and a.role is AssignmentRole.BAGNINO}
        am, pm = by_slot.get(AssignmentSlot.AM), by_slot.get(AssignmentSlot.PM)
        if am is None or pm is None or am.user_id == pm.user_id:
            continue
        if core_ids is not None and not {am.user_id, pm.user_id} <= core_ids:
            continue
        return am, pm
    raise AssertionError("no weekday with two distinct bagnino holders in this week")


def _core_ids(roster: dict[str, User]) -> set[int]:
    """§1: everyone but the jolly is a core worker with an H3 free day."""
    return {u.id for u in roster.values() if u.role is not UserRole.JOLLY}


# --- §5 permission tier ------------------------------------------------------


def test_override_requires_authentication(client: TestClient, session: DbSession) -> None:
    """§5: every capability starts at "authenticated and active"."""
    create_full_roster(session)
    resp = client.post(
        "/api/admin/override",
        json={
            "week": _future_monday().isoformat(),
            "day": "mon",
            "slot": "am",
            "role": "bagnino",
            "user_id": 1,
        },
    )
    assert resp.status_code == 401


def test_override_is_refused_to_a_plain_worker(client: TestClient, session: DbSession) -> None:
    """§5 row 4: "Override locked slots" is admin/root only."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    row = _rows(session, week)[0]
    login(client, "pasha")
    assert _override(client, week, row, roster["mattia"].id).status_code == 403


def test_root_inherits_the_override_capability(client: TestClient, session: DbSession) -> None:
    """§5: "Root inherits all admin capabilities" — via `is_root`, not `is_admin`
    (the fixture root has `is_admin=false`, so this proves inheritance)."""
    roster = create_full_roster(session)
    assert roster["matteo"].is_root and not roster["matteo"].is_admin
    week = _published_week(session, roster, _future_monday())
    am, _pm = _weekday_bagnino_pair(_rows(session, week))
    login(client, "matteo")
    resp = _override(client, week, am, roster["mattia"].id)
    assert resp.status_code == 200, resp.text


# --- preconditions -----------------------------------------------------------


def test_override_refuses_an_unlocked_week(client: TestClient, session: DbSession) -> None:
    """§3.4: post-lock changes are swap or override. A week that has only been
    SOLVED is changed by re-solving (§3.2), not by hand — 409."""
    roster = create_full_roster(session)
    week = get_or_create_week(session, _future_monday())
    run_solve(session, week)
    session.commit()
    assert week.status is WeekStatus.SOLVED
    row = next(a for a in _rows(session, week) if a.role is AssignmentRole.BAGNINO)

    login(client, "mattia")
    resp = _override(client, week, row, roster["mattia"].id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "week_not_locked"


def test_override_of_an_unknown_week_is_404(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    login(client, "mattia")
    resp = client.post(
        "/api/admin/override",
        json={
            "week": _future_monday(weeks_ahead=8).isoformat(),
            "day": "mon",
            "slot": "am",
            "role": "bagnino",
            "user_id": 1,
        },
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "week_not_found"


def test_override_refuses_a_role_incompatible_holder(
    client: TestClient, session: DbSession
) -> None:
    """§1/H1: role is a property of the person, and H1's coverage names QUALIFIED
    holders. This is the one rule an override may not bend — and it is checked by
    the same `app.roles.can_hold` predicate the §4 swap validator uses."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    bagnino_row = next(
        a for a in _rows(session, week) if a.role is AssignmentRole.BAGNINO and a.day in SOLVER_DAYS
    )
    login(client, "mattia")
    resp = _override(client, week, bagnino_row, roster["pasha"].id)  # a spiaggino
    assert resp.status_code == 422
    assert resp.json()["detail"] == "override_role_invalid"


def test_override_refuses_an_inactive_holder(client: TestClient, session: DbSession) -> None:
    """§5: deactivation is the only removal, and a removed worker is not an
    eligible holder — seating one would be a silent hole in the coverage."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    spare = create_user(session, "gone", role=UserRole.BAGNINO, active=False)
    row = next(
        a for a in _rows(session, week) if a.role is AssignmentRole.BAGNINO and a.day in SOLVER_DAYS
    )
    login(client, "mattia")
    resp = _override(client, week, row, spare.id)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "override_user_inactive"


def test_override_refuses_a_no_op(client: TestClient, session: DbSession) -> None:
    """An override that changes nothing must not write an audit row and fire two
    notifications claiming it did — 409, and the log stays clean."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    row = next(a for a in _rows(session, week) if a.day in SOLVER_DAYS)
    before = len(session.scalars(select(AuditLog)).all())

    login(client, "mattia")
    resp = _override(client, week, row, row.user_id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "override_no_change"
    session.expire_all()
    assert len(session.scalars(select(AuditLog)).all()) == before


# --- the change itself -------------------------------------------------------


def test_override_restamps_the_row_and_audits_it(client: TestClient, session: DbSession) -> None:
    """§5/§6: the row changes hands, its provenance becomes `override`, and the
    transition is audit-logged with both holders named."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    am, _pm = _weekday_bagnino_pair(_rows(session, week))
    displaced = am.user_id
    row_id = am.id

    login(client, "mattia")
    resp = _override(client, week, am, roster["mattia"].id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["previous_user_id"] == displaced
    assert body["new_user_id"] == roster["mattia"].id
    assert body["created"] is False
    assert body["assignment"]["source"] == AssignmentSource.OVERRIDE.value

    session.expire_all()
    row = session.get(Assignment, row_id)
    assert row is not None
    assert row.user_id == roster["mattia"].id
    assert row.source is AssignmentSource.OVERRIDE

    entry = session.scalars(
        select(AuditLog).where(AuditLog.action == "override").order_by(AuditLog.id.desc())
    ).first()
    assert entry is not None
    assert entry.actor_id == roster["mattia"].id
    assert entry.entity == "assignment" and entry.entity_id == row_id
    assert entry.payload is not None
    assert entry.payload["previous_user_id"] == displaced
    assert entry.payload["user_id"] == roster["mattia"].id
    assert "violations" in entry.payload, "§2.1: never silent about what it broke"


def test_override_notifies_both_affected_workers(client: TestClient, session: DbSession) -> None:
    """§12 Phase 6 gate criterion + §10 `admin_override`: BOTH the worker who lost
    the slot and the one who gained it are affected, so both are notified.

    Addressed individually, not by role — root is a working bagnino and hears
    about his own shifts (§5 hides the root ROLE from role-based fan-outs).
    """
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    am, _pm = _weekday_bagnino_pair(_rows(session, week))
    displaced = am.user_id
    gaining = roster["mattia"].id

    login(client, "mattia")
    assert _override(client, week, am, gaining).status_code == 200

    session.expire_all()
    notified = {
        n.user_id: n
        for n in session.scalars(
            select(Notification).where(Notification.event_type == EVENT_ADMIN_OVERRIDE)
        ).all()
    }
    assert set(notified) == {displaced, gaining}, "the loser AND the gainer (§12)"
    payload = notified[displaced].payload
    assert payload is not None
    # The §10 email template reads week/day/slot/role — they must be present.
    assert payload["week"] == week.monday_date.isoformat()
    assert payload["day"] == am.day.value
    assert payload["slot"] == am.slot.value
    assert payload["role"] == am.role.value
    assert payload["previous_user_id"] == displaced
    assert payload["user_id"] == gaining


def test_override_emails_both_affected_workers(
    client: TestClient, session: DbSession, email_outbox: Any
) -> None:
    """§10 Channel 2: the `admin_override` template renders for an opted-in user.

    This event was the last one in §10 with no emitter; the template existed but
    nothing had ever driven it.
    """
    roster = create_full_roster(session)
    for user in roster.values():
        user.email = f"{user.username}@example.test"
        user.email_notifications = True
    session.commit()
    week = _published_week(session, roster, _future_monday())
    am, _pm = _weekday_bagnino_pair(_rows(session, week))
    displaced = session.get(User, am.user_id)
    assert displaced is not None

    before = len(email_outbox.sent)
    login(client, "mattia")
    assert _override(client, week, am, roster["mattia"].id).status_code == 200

    recipients = {m.to for m in email_outbox.sent[before:]}
    assert f"{displaced.username}@example.test" in recipients
    assert "mattia@example.test" in recipients


def test_override_reports_the_h3_h4_violations_it_creates(
    client: TestClient, session: DbSession
) -> None:
    """§2.1 vs §5 — the deliberate asymmetry, pinned.

    H1–H7 bind the SOLVER (§2.1 "infeasibility triggers the sacrifice flow"; §8
    encodes them as model constraints). §5 grants the admin an override of the
    LOCKED result, and §3.4 makes it one of only two ways a locked slot moves at
    all. An override that refused every H2–H4 violation could not express the
    cases it exists for, so it is allowed — and returns what it broke, because
    §2.3's "never resolve silently" is the principle the whole system is built on.

    Seating the day's AM bagnino in the PM slot too gives him two slots that day
    (H4) and leaves the displaced worker with two free weekdays (H3).
    """
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    am, pm = _weekday_bagnino_pair(_rows(session, week), _core_ids(roster))
    doubled, displaced = am.user_id, pm.user_id

    login(client, "mattia")
    resp = _override(client, week, pm, doubled)
    assert resp.status_code == 200, "§5: the override is ALLOWED to break H2-H4"
    violations = resp.json()["violations"]
    # The doubled worker breaks H4 (two slots on one weekday); the displaced one
    # breaks H3 (a second free weekday). He does NOT break H3 himself — a second
    # slot on a day he already worked changes nothing about which days he is off.
    assert {(v["rule"], v["user_id"]) for v in violations} == {
        ("H4", doubled),
        ("H3", displaced),
    }, violations
    assert all(v["rule"] in {"H2", "H3", "H4"} for v in violations)


def test_override_of_a_clean_swap_reports_no_violations(
    client: TestClient, session: DbSession
) -> None:
    """The other half of the previous test: an override that keeps the week legal
    reports an EMPTY violation list, so a non-empty one always means something."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    # The jolly may hold either role and is exempt from H3/H4 (H6), so handing him
    # a weekday bagnino slot breaks nothing for him. The displaced core worker
    # gains a second free weekday, so pick a slot he can lose... there is none:
    # instead override a SUNDAY bagnino row, where H3/H4 do not range (H5).
    sun = next(a for a in rows if a.day is Day.SUN and a.role is AssignmentRole.BAGNINO)
    login(client, "mattia")
    resp = _override(client, week, sun, roster["mattia"].id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["violations"] == []


def test_override_never_serializes_is_root(client: TestClient, session: DbSession) -> None:
    """§5: `is_root` reaches the wire nowhere. Root is a working bagnino, so he
    appears in a schedule row as a holder — never as an authority."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    sun = next(
        a for a in _rows(session, week) if a.day is Day.SUN and a.role is AssignmentRole.BAGNINO
    )
    login(client, "mattia")
    resp = _override(client, week, sun, roster["mattia"].id)
    assert resp.status_code == 200, resp.text
    assert "is_root" not in resp.text


# --- H5 weekend: the ambiguous double-staffed slot ---------------------------


def test_a_double_staffed_weekend_slot_needs_the_row_named(
    client: TestClient, session: DbSession
) -> None:
    """§6/§2.1 H5: the unique index is scoped to Mon–Fri because the template
    seats TWO spiaggini in every weekend slot. `(week, day, slot, role)` therefore
    does not identify a row there, and the override refuses rather than replacing
    whichever one the database happened to return first."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    sat_spiaggini = [
        a
        for a in _rows(session, week)
        if a.day is Day.SAT and a.slot is AssignmentSlot.AM and a.role is AssignmentRole.SPIAGGINO
    ]
    assert len(sat_spiaggini) == 2, "H5 puts both spiaggini in every weekend slot"

    login(client, "mattia")
    resp = _override(client, week, sat_spiaggini[0], roster["mattia"].id)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "override_ambiguous_slot"

    # Naming the row resolves it.
    target = sat_spiaggini[0]
    resp = _override(client, week, target, roster["mattia"].id, assignment_id=target.id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["assignment"]["id"] == target.id


def test_an_assignment_id_that_contradicts_the_slot_is_refused(
    client: TestClient, session: DbSession
) -> None:
    """Two keys naming different rows is a client bug, not a preference: refuse
    rather than silently honouring one of them."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    sat = next(a for a in rows if a.day is Day.SAT and a.role is AssignmentRole.BAGNINO)
    other = next(a for a in rows if a.day in SOLVER_DAYS and a.role is AssignmentRole.BAGNINO)

    login(client, "mattia")
    resp = _override(client, week, sat, roster["mattia"].id, assignment_id=other.id)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "override_row_mismatch"


# --- §2.2 / H5: the alternation boundary. The mandated gate tests. -----------


def test_a_sunday_override_re_seeds_next_weeks_alternation_boundary(
    client: TestClient, session: DbSession
) -> None:
    """§2.1 H5 + §2.2: an override is the OTHER thing that can move a weekend row.

    `solver_state` holds each worker's LAST WORKED SLOT — a fact about what
    happened, not about what was planned. Publishing derives it from the weekend
    rows; an override then moves one, and §2.2 names Sunday as the seed for next
    Monday's alternation. If the boundary were not re-derived, next week's S2 term
    would be computed from a Sunday that did not happen.

    Mirrors `test_swaps_api.py::test_a_sunday_swap_re_seeds_next_weeks_alternation_boundary`
    — the swap path already does this (`app.swap_service` calls
    `write_solver_state`), and H5 makes the two instruments equals.
    """
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    sun_am = next(
        a
        for a in _rows(session, week)
        if a.day is Day.SUN and a.slot is AssignmentSlot.AM and a.role is AssignmentRole.BAGNINO
    )
    jolly = roster["mattia"]
    assert session.get(SolverState, jolly.id) is None, (
        "precondition: the jolly works no weekend template row, so he carries no boundary"
    )

    login(client, "mattia")
    assert _override(client, week, sun_am, jolly.id).status_code == 200

    session.expire_all()
    state = session.get(SolverState, jolly.id)
    assert state is not None, "the new Sunday holder must carry a boundary (§2.2)"
    assert state.last_worked_slot is AssignmentSlot.AM
    assert state.last_worked_date == week.monday_date + dt.timedelta(days=6)
    # And it agrees with the schedule as it now stands, not with the ideal template.
    sunday_row = next(
        a
        for a in _rows(session, week)
        if a.day is Day.SUN and a.user_id == jolly.id and a.role is AssignmentRole.BAGNINO
    )
    assert state.last_worked_slot == sunday_row.slot


def test_an_override_off_sunday_clears_the_vacated_boundary(
    client: TestClient, session: DbSession
) -> None:
    """§2.2: the `solver_state` write set is AUTHORITATIVE, not additive.

    The bagnino displaced from Sunday holds no Sunday row afterwards, so §2.2
    wants his boundary term ABSENT — exactly as the jolly's is when he works no
    weekend. A merely-upserting write would leave his stale row seeding next
    Monday from a Sunday he did not work.

    Mirrors `test_swaps_api.py::test_a_saturday_for_sunday_swap_clears_the_vacated_boundary`.
    """
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    sun_am = next(
        a
        for a in _rows(session, week)
        if a.day is Day.SUN and a.slot is AssignmentSlot.AM and a.role is AssignmentRole.BAGNINO
    )
    displaced_id = sun_am.user_id
    assert session.get(SolverState, displaced_id) is not None, (
        "precondition: the Sunday holder starts with a boundary"
    )

    login(client, "mattia")
    assert _override(client, week, sun_am, roster["mattia"].id).status_code == 200

    session.expire_all()
    remaining_sunday = {
        a.user_id
        for a in _rows(session, week)
        if a.day is Day.SUN and a.role is AssignmentRole.BAGNINO
    }
    assert displaced_id not in remaining_sunday, "precondition: he really left Sunday"
    assert session.get(SolverState, displaced_id) is None, (
        "a worker with no Sunday row must carry no boundary (§2.2)"
    )


def test_a_weekday_override_leaves_the_boundary_alone(
    client: TestClient, session: DbSession
) -> None:
    """The converse: §2.2's boundary is a fact about SUNDAY, so a Mon–Fri
    override must not disturb it. Without this, "re-derive on every override"
    could pass the two tests above while quietly rewriting unrelated state."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    am, _pm = _weekday_bagnino_pair(_rows(session, week))
    before = {
        s.user_id: (s.last_worked_slot, s.last_worked_date)
        for s in session.scalars(select(SolverState)).all()
    }
    assert before, "precondition: publishing seeded the boundary"

    login(client, "mattia")
    assert _override(client, week, am, roster["mattia"].id).status_code == 200

    session.expire_all()
    after = {
        s.user_id: (s.last_worked_slot, s.last_worked_date)
        for s in session.scalars(select(SolverState)).all()
    }
    assert after == before
