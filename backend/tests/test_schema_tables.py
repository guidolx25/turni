"""Spec §6: the ten tables and their columns, verbatim.

These assertions are transcribed from §6's block, not from `app/models.py`. Set
equality (not containment) is deliberate: §6 enumerates the columns, so a
dropped, renamed *or* silently added column is a deviation and must fail here.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, inspect

# spec §6, table by table, in the order the spec writes them.
SPEC_TABLES: dict[str, set[str]] = {
    "users": {
        "id",
        "username",
        "password_hash",
        "display_name",
        "role",
        "is_admin",
        "is_root",
        "email",
        "email_notifications",
        "language",
        "active",
        "created_at",
    },
    "sessions": {"id", "user_id", "created_at", "expires_at"},
    "weeks": {"id", "monday_date", "status", "solved_at", "locked_at"},
    "constraints": {
        "id",
        "user_id",
        "week_id",
        "day",
        "slot",
        "kind",
        "note",
        "created_at",
        "updated_at",
    },
    "assignments": {"id", "week_id", "day", "slot", "role", "user_id", "source"},
    "swap_requests": {
        "id",
        "week_id",
        "from_user",
        "to_user",
        "from_assignment",
        "to_assignment",
        "status",
        "created_at",
        "resolved_at",
    },
    "sacrifice_proposals": {
        "id",
        "week_id",
        "user_id",
        "proposed_free_day",
        "status",
        "conflict",
        "created_at",
    },
    "notifications": {"id", "user_id", "event_type", "payload", "read", "created_at"},
    "audit_log": {
        "id",
        "actor_id",
        "action",
        "entity",
        "entity_id",
        "payload",
        "created_at",
    },
    "solver_state": {"user_id", "last_worked_slot", "last_worked_date"},
}


def test_section6_declares_ten_tables() -> None:
    """Guards the transcription itself: §6 lists exactly ten tables."""
    assert len(SPEC_TABLES) == 10


def test_all_section6_tables_exist(engine: Engine) -> None:
    present = set(inspect(engine).get_table_names())
    # alembic_version is migration bookkeeping, not part of §6.
    assert set(SPEC_TABLES) <= present
    assert present - set(SPEC_TABLES) == {"alembic_version"}


@pytest.mark.parametrize("table", sorted(SPEC_TABLES))
def test_table_columns_match_section6(engine: Engine, table: str) -> None:
    columns = {column["name"] for column in inspect(engine).get_columns(table)}
    assert columns == SPEC_TABLES[table]


def test_solver_state_is_keyed_by_user_id_with_no_surrogate_id(engine: Engine) -> None:
    """§6: `solver_state(user_id PK, ...)` — one row per user, no `id` column."""
    inspector = inspect(engine)
    assert inspector.get_pk_constraint("solver_state")["constrained_columns"] == ["user_id"]
    assert "id" not in {column["name"] for column in inspector.get_columns("solver_state")}


@pytest.mark.parametrize("table", ["notifications", "audit_log"])
def test_payload_is_json(engine: Engine, table: str) -> None:
    """§6 annotates both payload columns `JSON`."""
    payload = next(c for c in inspect(engine).get_columns(table) if c["name"] == "payload")
    assert "JSON" in str(payload["type"]).upper()


def test_weeks_monday_date_is_a_date(engine: Engine) -> None:
    """§6 `weeks(monday_date ...)` identifies the week by its Monday — a date,
    not a timestamp (the §3 Sun 17:00 deadline is derived, not stored)."""
    column = next(c for c in inspect(engine).get_columns("weeks") if c["name"] == "monday_date")
    assert str(column["type"]).upper() == "DATE"


def test_solver_state_last_worked_date_is_a_date(engine: Engine) -> None:
    """§6 solver_state(..., last_worked_date) — §8 writes a calendar date."""
    column = next(
        c for c in inspect(engine).get_columns("solver_state") if c["name"] == "last_worked_date"
    )
    assert str(column["type"]).upper() == "DATE"
