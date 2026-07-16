"""Spec §6: the unique keys, proven by making the database refuse a duplicate.

Reading a UNIQUE clause out of the DDL would only prove it was declared; these
tests insert the duplicate and require an IntegrityError, so they also catch a
constraint that exists but is not enforced (a real SQLite hazard — see the FK
pragma tests below).
"""

from __future__ import annotations

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from tests.helpers import (
    FIXED_TS,
    make_assignment,
    make_constraint,
    make_user,
    make_week,
)


def test_users_username_is_unique(connection: Connection) -> None:
    """§6 users(username UNIQUE) — the §7 login key."""
    make_user(connection, username="matteo")
    with pytest.raises(IntegrityError):
        make_user(connection, username="matteo", display_name="Impostor")


def test_weeks_monday_date_is_unique(connection: Connection) -> None:
    """§6 weeks(monday_date UNIQUE) — one row per calendar week."""
    make_week(connection, monday_date="2026-07-13")
    with pytest.raises(IntegrityError):
        make_week(connection, monday_date="2026-07-13", status="locked")


def test_weeks_accepts_distinct_mondays(connection: Connection) -> None:
    """Control for the test above: the constraint is on the date, not the table."""
    make_week(connection, monday_date="2026-07-13")
    make_week(connection, monday_date="2026-07-20")
    assert connection.execute(text("SELECT count(*) FROM weeks")).scalar_one() == 2


def test_h1_one_holder_per_weekday_slot_role(connection: Connection) -> None:
    """§6 assignments UNIQUE(week_id, day, slot, role) WHERE day IN (mon..fri).

    This is H1's "exactly one bagnino and exactly one spiaggino per slot" held by
    the database rather than by the solver, for the Mon–Fri rows it governs: two
    people cannot occupy the same role in the same weekday slot even if a swap or
    an override tried to write it.
    """
    week_id = make_week(connection)
    matteo = make_user(connection, username="matteo")
    francesco = make_user(connection, username="francesco")
    make_assignment(
        connection, user_id=matteo, week_id=week_id, day="mon", slot="am", role="bagnino"
    )
    with pytest.raises(IntegrityError):
        make_assignment(
            connection, user_id=francesco, week_id=week_id, day="mon", slot="am", role="bagnino"
        )


@pytest.mark.parametrize("weekend_day", ["sat", "sun"])
def test_weekend_slot_allows_two_spiaggini(connection: Connection, weekend_day: str) -> None:
    """§6 (amended): the unique index is weekday-only, so it exempts weekend rows.

    H5 puts BOTH spiaggini (Pasha and Amir) in the same Sat/Sun slot full-day; a
    table-wide UNIQUE(week, day, slot, role) would reject the second. The weekday
    scope lets them coexist — their integrity comes from `emit_weekend_template`
    being the sole writer, not from the DB key.
    """
    week_id = make_week(connection)
    pasha = make_user(connection, username="pasha", role="spiaggino")
    amir = make_user(connection, username="amir", role="spiaggino")
    for uid in (pasha, amir):
        make_assignment(
            connection,
            user_id=uid,
            week_id=week_id,
            day=weekend_day,
            slot="am",
            role="spiaggino",
            source="weekend_template",
        )
    assert connection.execute(text("SELECT count(*) FROM assignments")).scalar_one() == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [("day", "tue"), ("slot", "pm"), ("role", "spiaggino")],
)
def test_assignment_key_is_the_full_four_column_tuple(
    connection: Connection, field: str, value: str
) -> None:
    """Control: varying any one component of (week, day, slot, role) is allowed —
    so the test above fails for the duplicate, not for a too-narrow key."""
    week_id = make_week(connection)
    matteo = make_user(connection, username="matteo")
    francesco = make_user(connection, username="francesco")
    base = {"day": "mon", "slot": "am", "role": "bagnino"}
    make_assignment(connection, user_id=matteo, week_id=week_id, **base)
    make_assignment(connection, user_id=francesco, week_id=week_id, **{**base, field: value})
    assert connection.execute(text("SELECT count(*) FROM assignments")).scalar_one() == 2


def test_assignment_key_ignores_user_id(connection: Connection) -> None:
    """The same person may hold the same slot in both roles across the week —
    H6 lets Mattia work both slots of a day — so user_id is not part of the key,
    and a duplicate (week, day, slot, role) is rejected even for the same user."""
    week_id = make_week(connection)
    mattia = make_user(connection, username="mattia", role="jolly")
    make_assignment(
        connection, user_id=mattia, week_id=week_id, day="tue", slot="am", role="bagnino"
    )
    make_assignment(
        connection, user_id=mattia, week_id=week_id, day="tue", slot="pm", role="spiaggino"
    )
    with pytest.raises(IntegrityError):
        make_assignment(
            connection, user_id=mattia, week_id=week_id, day="tue", slot="am", role="bagnino"
        )


def test_constraint_upsert_key_is_user_week_day_slot(connection: Connection) -> None:
    """§6 (v1.1) constraints UNIQUE(user_id, week_id, day, slot) — §3's upsert key.

    Without this, a re-submission would append a second, contradictory row and
    'upsert on (user, week, day, slot)' would have no well-defined target.
    """
    user_id = make_user(connection)
    week_id = make_week(connection)
    make_constraint(connection, user_id=user_id, week_id=week_id, day="mon", slot="am", kind="hard")
    with pytest.raises(IntegrityError):
        make_constraint(
            connection, user_id=user_id, week_id=week_id, day="mon", slot="am", kind="soft"
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("day", "tue"), ("slot", "pm")],
)
def test_constraint_key_is_the_full_four_column_tuple(
    connection: Connection, field: str, value: str
) -> None:
    """Control: a different day or slot for the same user/week is a distinct row."""
    user_id = make_user(connection)
    week_id = make_week(connection)
    base = {"day": "mon", "slot": "am"}
    make_constraint(connection, user_id=user_id, week_id=week_id, **base)
    make_constraint(connection, user_id=user_id, week_id=week_id, **{**base, field: value})
    assert connection.execute(text("SELECT count(*) FROM constraints")).scalar_one() == 2


def test_constraint_key_separates_users_and_weeks(connection: Connection) -> None:
    """Control: §3 supports multi-week submission, and two workers may of course
    be unavailable in the same slot."""
    week_a = make_week(connection, monday_date="2026-07-13")
    week_b = make_week(connection, monday_date="2026-07-20")
    pasha = make_user(connection, username="pasha")
    amir = make_user(connection, username="amir")
    for user_id in (pasha, amir):
        for week_id in (week_a, week_b):
            make_constraint(connection, user_id=user_id, week_id=week_id, day="mon", slot="am")
    assert connection.execute(text("SELECT count(*) FROM constraints")).scalar_one() == 4


def test_solver_state_allows_one_row_per_user(connection: Connection) -> None:
    """§6 solver_state(user_id PK): the primary key is the user, so a second row
    for the same worker is impossible — no surrogate id can hide a duplicate."""
    user_id = make_user(connection)
    connection.execute(
        text(
            "INSERT INTO solver_state (user_id, last_worked_slot, last_worked_date)"
            " VALUES (:u, 'pm', '2026-07-12')"
        ),
        {"u": user_id},
    )
    with pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO solver_state (user_id, last_worked_slot, last_worked_date)"
                " VALUES (:u, 'am', '2026-07-12')"
            ),
            {"u": user_id},
        )


def test_foreign_keys_are_enforced_on_the_app_engine() -> None:
    """`PRAGMA foreign_keys` is off by default and per connection; `app.db`
    installs a connect listener. If that listener regressed, every FK in §6 would
    be decorative — including assignments.user_id."""
    from app.db import engine

    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1


def test_assignment_requires_an_existing_user(connection: Connection) -> None:
    """The `connection` fixture asserts the pragma is on, so this is a real test."""
    week_id = make_week(connection)
    with pytest.raises(IntegrityError):
        make_assignment(connection, user_id=999_999, week_id=week_id)


def test_constraint_requires_an_existing_week(connection: Connection) -> None:
    user_id = make_user(connection)
    with pytest.raises(IntegrityError):
        make_constraint(connection, user_id=user_id, week_id=999_999)


def test_notification_requires_an_existing_user(connection: Connection) -> None:
    with pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO notifications (user_id, event_type, read, created_at)"
                " VALUES (999999, 'schedule_published', 0, :ts)"
            ),
            {"ts": FIXED_TS},
        )
