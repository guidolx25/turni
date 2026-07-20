"""Raw-SQL row builders for the §6 schema tests.

The ORM is deliberately bypassed here. `app.enums` would reject a bad value in
Python long before it reached SQLite, which would make a test about the *DDL*
pass for the wrong reason: the point is to prove the database itself refuses
`assignments.slot = 'full_day'`, so the insert must go in as literal SQL.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Connection, text

# Any fixed timestamp: these rows exist to exercise constraints, never clocks.
FIXED_TS = "2026-07-13 08:00:00.000000"
FIXED_MONDAY = "2026-07-13"


def insert(connection: Connection, table: str, **values: Any) -> int:
    """INSERT one row of literal values; returns the new rowid."""
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    result = connection.execute(
        text(f'INSERT INTO "{table}" ({columns}) VALUES ({placeholders})'), values
    )
    return int(result.lastrowid or 0)


def make_user(connection: Connection, **overrides: Any) -> int:
    row: dict[str, Any] = {
        "username": "worker",
        "password_hash": "argon2-placeholder",
        "display_name": "Worker",
        "role": "bagnino",
        "is_admin": 0,
        "is_root": 0,
        "email": None,
        "email_notifications": 1,
        "language": "it",
        "active": 1,
        "created_at": FIXED_TS,
    }
    row.update(overrides)
    return insert(connection, "users", **row)


def make_week(connection: Connection, **overrides: Any) -> int:
    row: dict[str, Any] = {"monday_date": FIXED_MONDAY, "status": "open"}
    row.update(overrides)
    return insert(connection, "weeks", **row)


def make_constraint(connection: Connection, *, user_id: int, week_id: int, **overrides: Any) -> int:
    row: dict[str, Any] = {
        "user_id": user_id,
        "week_id": week_id,
        "day": "mon",
        "slot": "am",
        "kind": "hard",
        "note": None,
        "created_at": FIXED_TS,
        "updated_at": FIXED_TS,
    }
    row.update(overrides)
    return insert(connection, "constraints", **row)


def make_sacrifice_proposal(
    connection: Connection, *, user_id: int, week_id: int, **overrides: Any
) -> int:
    row: dict[str, Any] = {
        "week_id": week_id,
        "user_id": user_id,
        "proposed_free_day": "fri",
        "status": "pending",
        "conflict": None,
        "created_at": FIXED_TS,
    }
    row.update(overrides)
    return insert(connection, "sacrifice_proposals", **row)


def make_assignment(connection: Connection, *, user_id: int, week_id: int, **overrides: Any) -> int:
    row: dict[str, Any] = {
        "week_id": week_id,
        "day": "mon",
        "slot": "am",
        "role": "bagnino",
        "user_id": user_id,
        "source": "solver",
    }
    row.update(overrides)
    return insert(connection, "assignments", **row)


def check_constraint_domain(connection: Connection, table: str, column: str) -> set[str]:
    """The value set SQLite will actually accept for an enum column.

    Read out of the table's own DDL (`sqlite_master.sql`) rather than from
    `app.enums`, so the assertion is about the database, not about Python.
    """
    ddl = connection.execute(
        text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :name"),
        {"name": table},
    ).scalar_one()
    pattern = re.compile(rf"CHECK\s*\(\s*{re.escape(column)}\s+IN\s*\(([^)]*)\)", re.IGNORECASE)
    match = pattern.search(ddl)
    if match is None:
        raise AssertionError(f"{table}.{column} has no CHECK ... IN (...) domain in:\n{ddl}")
    return set(re.findall(r"'([^']*)'", match.group(1)))
