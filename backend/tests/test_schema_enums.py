"""Spec §6: enum domains, as the database enforces them.

Every assertion here reads or exercises the DDL. SQLite has no ENUM type, so
`app.db.enum_column` compiles each §6 ENUM to VARCHAR + CHECK; if that ever
degrades to a bare VARCHAR the domain tests below stop finding a CHECK and fail
loudly rather than silently accepting anything.

The two deliberate near-misses of §6 — `constraints.slot ENUM(am,pm,full_day)`
vs `assignments.slot ENUM(am,pm)`, and `users.role ENUM(bagnino,spiaggino,jolly)`
vs `assignments.role ENUM(bagnino,spiaggino)` — get their own tests: collapsing
either pair would let an unschedulable row into the database.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from tests.helpers import (
    FIXED_TS,
    check_constraint_domain,
    make_assignment,
    make_constraint,
    make_user,
    make_week,
)

DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}

# (table, column) -> the value set spec §6 writes for it.
SPEC_ENUM_DOMAINS: dict[tuple[str, str], set[str]] = {
    ("users", "role"): {"bagnino", "spiaggino", "jolly"},
    ("users", "language"): {"it", "en"},
    ("weeks", "status"): {"open", "locked"},
    ("constraints", "day"): DAYS,
    ("constraints", "slot"): {"am", "pm", "full_day"},
    ("constraints", "kind"): {"hard", "soft"},
    ("assignments", "slot"): {"am", "pm"},
    ("assignments", "role"): {"bagnino", "spiaggino"},
    ("assignments", "source"): {"solver", "weekend_template", "swap", "override"},
    ("swap_requests", "status"): {
        "pending",
        "accepted",
        "rejected",
        "expired",
        "pending_admin",
        "applied",
    },
    ("sacrifice_proposals", "status"): {"pending", "accepted", "declined"},
    ("sacrifice_proposals", "proposed_free_day"): DAYS,
    ("solver_state", "last_worked_slot"): {"am", "pm"},
}


@pytest.mark.parametrize(("table", "column"), sorted(SPEC_ENUM_DOMAINS))
def test_enum_column_domain_matches_section6(
    connection: Connection, table: str, column: str
) -> None:
    """The CHECK in the shipped DDL admits exactly §6's values — no more, no less."""
    assert check_constraint_domain(connection, table, column) == SPEC_ENUM_DOMAINS[(table, column)]


def test_constraints_slot_accepts_full_day(connection: Connection) -> None:
    """§6 constraints.slot ENUM(am, pm, full_day) — §3's day-level unavailability."""
    user_id = make_user(connection)
    week_id = make_week(connection)
    make_constraint(connection, user_id=user_id, week_id=week_id, slot="full_day")
    stored = connection.execute(text("SELECT slot FROM constraints")).scalar_one()
    assert stored == "full_day"


def test_assignments_slot_rejects_full_day(connection: Connection) -> None:
    """§6 assignments.slot ENUM(am, pm): an assignment is always a concrete slot.

    H5's "Pasha and Amir full-day" weekend rows are therefore two rows (am + pm),
    never one 'full_day' row. Collapsing ConstraintSlot and AssignmentSlot into a
    single type would make this pass — which is exactly what must not happen.
    """
    user_id = make_user(connection)
    week_id = make_week(connection)
    with pytest.raises(IntegrityError):
        make_assignment(connection, user_id=user_id, week_id=week_id, slot="full_day")


def test_solver_state_last_worked_slot_rejects_full_day(connection: Connection) -> None:
    """§6 solver_state.last_worked_slot ENUM(am, pm) — §8 persists a real slot."""
    user_id = make_user(connection)
    with pytest.raises(IntegrityError):
        connection.execute(
            text("INSERT INTO solver_state (user_id, last_worked_slot) VALUES (:u, 'full_day')"),
            {"u": user_id},
        )


def test_assignments_role_rejects_jolly(connection: Connection) -> None:
    """§6 assignments.role ENUM(bagnino, spiaggino): 'jolly' is a *user* role.

    Mattia is a jolly (users.role), but every slot he works is worked as one
    concrete role — H1 counts bagnini and spiaggini, not jollies.
    """
    user_id = make_user(connection, role="jolly")
    week_id = make_week(connection)
    with pytest.raises(IntegrityError):
        make_assignment(connection, user_id=user_id, week_id=week_id, role="jolly")


def test_users_role_accepts_jolly(connection: Connection) -> None:
    """§6 users.role ENUM(bagnino, spiaggino, jolly) — Mattia (§1)."""
    make_user(connection, username="mattia", role="jolly")
    stored = connection.execute(
        text("SELECT role FROM users WHERE username = 'mattia'")
    ).scalar_one()
    assert stored == "jolly"


def test_assignments_day_accepts_weekend_days(connection: Connection) -> None:
    """H5: the weekend template is emitted as rows, so sat/sun must be storable
    even though the solver only ranges over Mon–Fri."""
    user_id = make_user(connection)
    week_id = make_week(connection)
    for day in ("sat", "sun"):
        make_assignment(
            connection, user_id=user_id, week_id=week_id, day=day, source="weekend_template"
        )
    stored = set(connection.execute(text("SELECT day FROM assignments")).scalars())
    assert stored == {"sat", "sun"}


@pytest.mark.parametrize("bad_value", ["AM", "full-day", "", "anything"])
def test_assignments_slot_rejects_values_outside_the_domain(
    connection: Connection, bad_value: str
) -> None:
    """Including 'AM': §6's values are the lowercase strings, so the uppercase
    Python member *name* is not a legal stored value."""
    user_id = make_user(connection)
    week_id = make_week(connection)
    with pytest.raises(IntegrityError):
        make_assignment(connection, user_id=user_id, week_id=week_id, slot=bad_value)


@pytest.mark.parametrize("bad_value", ["BAGNINO", "JOLLY", "Bagnino", "lifeguard", "admin"])
def test_users_role_rejects_values_outside_the_domain(
    connection: Connection, bad_value: str
) -> None:
    """§6 users.role ENUM(bagnino, spiaggino, jolly). Note 'admin' is not a role:
    §5 makes admin/root flags on the row, not values in this enum."""
    with pytest.raises(IntegrityError):
        make_user(connection, username=f"u-{bad_value}", role=bad_value)


@pytest.mark.parametrize("bad_value", ["IT", "fr", "italiano"])
def test_users_language_rejects_values_outside_the_domain(
    connection: Connection, bad_value: str
) -> None:
    with pytest.raises(IntegrityError):
        make_user(connection, username=f"u-{bad_value}", language=bad_value)


@pytest.mark.parametrize("bad_value", ["OPEN", "closed", "published"])
def test_weeks_status_rejects_values_outside_the_domain(
    connection: Connection, bad_value: str
) -> None:
    """§6 weeks.status ENUM(open, locked): §3's lifecycle has exactly two states."""
    with pytest.raises(IntegrityError):
        make_week(connection, monday_date=f"2026-07-{20}", status=bad_value)


@pytest.mark.parametrize("bad_value", ["PENDING", "cancelled", "pending_approval"])
def test_swap_status_rejects_values_outside_the_domain(
    connection: Connection, bad_value: str
) -> None:
    """§6/§4 swap state machine: pending, accepted, rejected, expired,
    pending_admin, applied — and nothing else."""
    user_id = make_user(connection)
    week_id = make_week(connection)
    a1 = make_assignment(connection, user_id=user_id, week_id=week_id, slot="am")
    a2 = make_assignment(connection, user_id=user_id, week_id=week_id, slot="pm")
    with pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO swap_requests"
                " (week_id, from_user, to_user, from_assignment, to_assignment, status, created_at)"
                " VALUES (:w, :u, :u, :a1, :a2, :status, :ts)"
            ),
            {"w": week_id, "u": user_id, "a1": a1, "a2": a2, "status": bad_value, "ts": FIXED_TS},
        )


@pytest.mark.parametrize("bad_value", ["PENDING", "rejected", "refused"])
def test_sacrifice_status_rejects_values_outside_the_domain(
    connection: Connection, bad_value: str
) -> None:
    """§2.3 requires an explicit accept/decline — 'declined', not 'rejected'."""
    user_id = make_user(connection)
    week_id = make_week(connection)
    with pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO sacrifice_proposals"
                " (week_id, user_id, proposed_free_day, status, created_at)"
                " VALUES (:w, :u, 'tue', :status, :ts)"
            ),
            {"w": week_id, "u": user_id, "status": bad_value, "ts": FIXED_TS},
        )


@pytest.mark.parametrize("bad_value", ["SOLVER", "manual", "admin"])
def test_assignment_source_rejects_values_outside_the_domain(
    connection: Connection, bad_value: str
) -> None:
    """§6 assignments.source ENUM(solver, weekend_template, swap, override) —
    the four ways a row can come into existence per §3/§4/§5."""
    user_id = make_user(connection)
    week_id = make_week(connection)
    with pytest.raises(IntegrityError):
        make_assignment(connection, user_id=user_id, week_id=week_id, source=bad_value)
