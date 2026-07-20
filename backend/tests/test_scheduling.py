"""Window-deadline arithmetic (spec §3.1) — pure, DST-sensitive.

The load-bearing property is that "Sunday 17:00 Europe/Rome" resolves to a
*different* UTC instant across the DST boundary (15:00 UTC in summer, 16:00 UTC
in winter). A naive `date - 1 day at 17:00 UTC` would be silently wrong by an
hour for half the year, so these tests pin the exact UTC result on both sides.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.enums import WeekStatus
from app.models import Week
from app.scheduling import ensure_monday, is_submittable, window_deadline

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase3


def _week(monday: dt.date, status: WeekStatus = WeekStatus.OPEN) -> Week:
    """A detached Week row — is_submittable/window_deadline read only its fields."""
    return Week(monday_date=monday, status=status)


def test_summer_deadline_is_1500_utc() -> None:
    """CEST (UTC+2): Sunday 2026-07-12 17:00 Rome → 15:00 UTC before the 07-13 week."""
    deadline = window_deadline(dt.date(2026, 7, 13))
    assert deadline == dt.datetime(2026, 7, 12, 15, 0, tzinfo=dt.UTC)


def test_winter_deadline_is_1600_utc() -> None:
    """CET (UTC+1): Sunday 2026-01-11 17:00 Rome → 16:00 UTC before the 01-12 week."""
    deadline = window_deadline(dt.date(2026, 1, 12))
    assert deadline == dt.datetime(2026, 1, 11, 16, 0, tzinfo=dt.UTC)


def test_deadline_returns_utc_aware() -> None:
    assert window_deadline(dt.date(2026, 7, 13)).tzinfo is dt.UTC


def test_ensure_monday_rejects_non_monday() -> None:
    with pytest.raises(ValueError, match="Monday"):
        ensure_monday(dt.date(2026, 7, 14))  # a Tuesday
    # A Monday passes silently.
    ensure_monday(dt.date(2026, 7, 13))


def test_window_deadline_rejects_non_monday() -> None:
    with pytest.raises(ValueError, match="Monday"):
        window_deadline(dt.date(2026, 7, 15))  # a Wednesday


def test_is_submittable_true_before_deadline_when_open() -> None:
    monday = dt.date(2026, 7, 13)
    before = window_deadline(monday) - dt.timedelta(minutes=1)
    assert is_submittable(_week(monday), now=before) is True


def test_is_submittable_false_after_deadline() -> None:
    monday = dt.date(2026, 7, 13)
    after = window_deadline(monday) + dt.timedelta(minutes=1)
    assert is_submittable(_week(monday), now=after) is False


def test_is_submittable_false_when_locked_even_before_deadline() -> None:
    """A locked week refuses edits regardless of the clock (§3.1 → §3.3)."""
    monday = dt.date(2026, 7, 13)
    before = window_deadline(monday) - dt.timedelta(hours=1)
    assert is_submittable(_week(monday, WeekStatus.LOCKED), now=before) is False
