"""The UTC invariant: store UTC in the DB, convert at the edges.

Spec §3 puts every deadline in Europe/Rome, a zone that is +01:00 in winter and
+02:00 in summer. A naive datetime is therefore not merely untidy — it is an
instant that is wrong by one or two hours depending on the date, which is
exactly the kind of bug that would move the Sunday 17:00 window close. These
tests pin the behaviour of `app.db.UtcDateTime` at the type layer, where the
invariant is cheap to hold, and read the raw stored text to prove what actually
landed in SQLite.

All timestamps are fixed literals: nothing here reads the wall clock except
`test_utcnow_is_tz_aware_utc`, which asserts only the tzinfo.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from app.db import utcnow
from app.enums import UserRole
from app.models import User
from tests.helpers import FIXED_TS

ROME = ZoneInfo("Europe/Rome")


def _user(**overrides: object) -> User:
    fields: dict[str, object] = {
        "username": "matteo",
        "password_hash": "argon2-placeholder",
        "display_name": "Matteo",
        "role": UserRole.BAGNINO,
    }
    fields.update(overrides)
    return User(**fields)


def test_naive_datetime_is_rejected(session: Session) -> None:
    """A naive value has no instant; refusing it is the whole point of the type."""
    session.add(_user(created_at=dt.datetime(2026, 7, 13, 12, 0, 0)))
    with pytest.raises(StatementError) as excinfo:
        session.flush()
    assert isinstance(excinfo.value.orig, ValueError)


@pytest.mark.parametrize(
    ("local", "expected_utc_hour"),
    [
        # Rome is UTC+2 in July (CEST) ...
        (dt.datetime(2026, 7, 13, 19, 0, tzinfo=ROME), 17),
        # ... and UTC+1 in January (CET). Same wall clock, different instant.
        (dt.datetime(2026, 1, 13, 19, 0, tzinfo=ROME), 18),
    ],
)
def test_rome_datetime_round_trips_as_utc(
    session: Session, local: dt.datetime, expected_utc_hour: int
) -> None:
    """A tz-aware non-UTC value is converted, not truncated: the instant survives."""
    session.add(_user(created_at=local))
    session.commit()
    session.expire_all()

    stored = session.get(User, 1)
    assert stored is not None
    assert stored.created_at.tzinfo is not None
    assert stored.created_at.utcoffset() == dt.timedelta(0)
    assert stored.created_at.hour == expected_utc_hour
    assert stored.created_at == local


def test_stored_text_carries_no_offset_and_is_utc(session: Session, connection: Connection) -> None:
    """What SQLite holds is the UTC wall clock — a reader that ignores tzinfo (or
    a `sqlite3 .backup` inspected by hand) still sees UTC, never Rome local."""
    session.add(_user(created_at=dt.datetime(2026, 7, 13, 19, 0, tzinfo=ROME)))
    session.commit()

    raw = connection.execute(text("SELECT created_at FROM users")).scalar_one()
    assert str(raw).startswith("2026-07-13 17:00:00")
    assert "+" not in str(raw)


def test_utc_datetime_read_back_from_a_legacy_naive_row_is_utc(
    session: Session, connection: Connection
) -> None:
    """Rows written outside the ORM (a migration backfill, a manual fix) come back
    tz-aware and interpreted as UTC, never as local time."""
    connection.execute(
        text(
            "INSERT INTO users (id, username, password_hash, display_name, role, is_admin,"
            " is_root, email_notifications, language, active, created_at)"
            " VALUES (1, 'matteo', 'h', 'Matteo', 'bagnino', 0, 0, 1, 'it', 1, :ts)"
        ),
        {"ts": FIXED_TS},
    )
    connection.commit()

    stored = session.get(User, 1)
    assert stored is not None
    assert stored.created_at == dt.datetime(2026, 7, 13, 8, 0, tzinfo=dt.UTC)


def test_utcnow_is_tz_aware_utc() -> None:
    """§6's created_at defaults go through `utcnow`; a naive default would be
    rejected by the bind param above, so this is the invariant's other half."""
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == dt.timedelta(0)


def test_nullable_timestamps_stay_none(session: Session) -> None:
    """§6 weeks(solved_at, locked_at) are empty until §3's solve and lock."""
    from app.models import Week

    week = Week(monday_date=dt.date(2026, 7, 13))
    session.add(week)
    session.commit()
    session.expire_all()

    stored = session.get(Week, week.id)
    assert stored is not None
    assert stored.solved_at is None
    assert stored.locked_at is None
