"""H5 weekend-template emission (§H5/§6) — pure, no DB.

Asserts the EXACT fixed pattern every Saturday/Sunday slot must carry, that every
row is stamped `source=weekend_template`, and that NO Mon–Fri row is ever emitted
(the solver owns Mon–Fri, §8).
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.enums import AssignmentRole, AssignmentSlot, AssignmentSource, Day
from app.solver.weekend import emit_weekend_template
from tests.solver.fixtures import (
    AMIR,
    FRANCESCO,
    MATTEO,
    PASHA,
    SPIAGGINO_CORE_IDS,
    WEEK_MONDAY,
    roster,
)

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase2

# H5 exact expected slots as (day, slot, role, worker_id). Two bagnino rows and
# four spiaggino rows (both spiaggini, full-day) per weekend day.
SATURDAY = WEEK_MONDAY + dt.timedelta(days=5)
SUNDAY = WEEK_MONDAY + dt.timedelta(days=6)

_EXPECTED: set[tuple[Day, AssignmentSlot, AssignmentRole, int]] = {
    # Saturday: Matteo AM, Francesco PM (bagnini); Pasha + Amir full-day.
    (Day.SAT, AssignmentSlot.AM, AssignmentRole.BAGNINO, MATTEO),
    (Day.SAT, AssignmentSlot.PM, AssignmentRole.BAGNINO, FRANCESCO),
    (Day.SAT, AssignmentSlot.AM, AssignmentRole.SPIAGGINO, PASHA),
    (Day.SAT, AssignmentSlot.PM, AssignmentRole.SPIAGGINO, PASHA),
    (Day.SAT, AssignmentSlot.AM, AssignmentRole.SPIAGGINO, AMIR),
    (Day.SAT, AssignmentSlot.PM, AssignmentRole.SPIAGGINO, AMIR),
    # Sunday: Francesco AM, Matteo PM (bagnini); Pasha + Amir full-day.
    (Day.SUN, AssignmentSlot.AM, AssignmentRole.BAGNINO, FRANCESCO),
    (Day.SUN, AssignmentSlot.PM, AssignmentRole.BAGNINO, MATTEO),
    (Day.SUN, AssignmentSlot.AM, AssignmentRole.SPIAGGINO, PASHA),
    (Day.SUN, AssignmentSlot.PM, AssignmentRole.SPIAGGINO, PASHA),
    (Day.SUN, AssignmentSlot.AM, AssignmentRole.SPIAGGINO, AMIR),
    (Day.SUN, AssignmentSlot.PM, AssignmentRole.SPIAGGINO, AMIR),
}


def test_emits_exact_h5_pattern() -> None:
    rows = emit_weekend_template(roster(), WEEK_MONDAY)
    got = {(r.day, r.slot, r.role, r.worker_id) for r in rows}
    assert got == _EXPECTED
    # No duplicates: the set size must equal the tuple length.
    assert len(rows) == len(_EXPECTED)


def test_every_row_is_weekend_template_source() -> None:
    rows = emit_weekend_template(roster(), WEEK_MONDAY)
    assert all(r.source is AssignmentSource.WEEKEND_TEMPLATE for r in rows)


def test_no_weekday_row_is_emitted() -> None:
    rows = emit_weekend_template(roster(), WEEK_MONDAY)
    # The solver owns Mon–Fri (§8); the template must never touch those days.
    assert all(r.day in (Day.SAT, Day.SUN) for r in rows)
    weekdays = {Day.MON, Day.TUE, Day.WED, Day.THU, Day.FRI}
    assert not any(r.day in weekdays for r in rows)


def test_rows_carry_the_concrete_weekend_dates() -> None:
    rows = emit_weekend_template(roster(), WEEK_MONDAY)
    for r in rows:
        expected = SATURDAY if r.day is Day.SAT else SUNDAY
        assert r.date == expected


def test_spiaggini_work_full_day_both_weekend_days() -> None:
    rows = emit_weekend_template(roster(), WEEK_MONDAY)
    for sp in SPIAGGINO_CORE_IDS:
        for day in (Day.SAT, Day.SUN):
            slots = {r.slot for r in rows if r.worker_id == sp and r.day is day}
            assert slots == {AssignmentSlot.AM, AssignmentSlot.PM}
            assert all(
                r.role is AssignmentRole.SPIAGGINO
                for r in rows
                if r.worker_id == sp and r.day is day
            )


def test_non_monday_input_is_rejected() -> None:
    import pytest

    # A Tuesday — the lifecycle only ever hands the template a week's Monday.
    with pytest.raises(ValueError, match="Monday"):
        emit_weekend_template(roster(), dt.date(2026, 7, 14))
