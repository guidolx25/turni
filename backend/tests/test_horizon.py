"""§3: a rolling horizon of open weeks always exists.

Weeks used to be materialised only by the first constraint submitted for them,
or by the solve job. That is a deadlock, and the deployment reached it: the cron
created and solved the upcoming week, its window shut at Sunday 17:00, and from
then on the only week in the database was closed. §3 says a constraint may be
submitted for "any future week with status open" — there were none, and the one
remaining thing that could have created one was a submission.

So the horizon's job is not convenience. It is that the app cannot talk itself
into a state where no one can submit anything.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.enums import WeekStatus
from app.models import Week
from app.scheduling import HORIZON_WEEKS, ensure_horizon, upcoming_submittable_monday

pytestmark = pytest.mark.phase6


def _at(iso: str) -> dt.datetime:
    """A UTC instant from an ISO string, for readable test times."""
    return dt.datetime.fromisoformat(iso).replace(tzinfo=dt.UTC)


def _mondays(db: DbSession) -> list[dt.date]:
    return list(db.scalars(select(Week.monday_date).order_by(Week.monday_date)).all())


def test_the_horizon_creates_the_configured_number_of_weeks(session: DbSession) -> None:
    ensure_horizon(session, _at("2026-07-22T12:00"))

    assert len(_mondays(session)) == HORIZON_WEEKS


def test_every_horizon_week_is_open(session: DbSession) -> None:
    """A week the horizon mints must be submittable, or it has done nothing."""
    ensure_horizon(session, _at("2026-07-22T12:00"))

    weeks = session.scalars(select(Week)).all()
    assert [w.status for w in weeks] == [WeekStatus.OPEN] * HORIZON_WEEKS


def test_horizon_weeks_are_consecutive_mondays(session: DbSession) -> None:
    ensure_horizon(session, _at("2026-07-22T12:00"))

    mondays = _mondays(session)
    assert mondays == [mondays[0] + dt.timedelta(weeks=i) for i in range(HORIZON_WEEKS)]
    assert all(m.weekday() == 0 for m in mondays)


def test_the_horizon_is_idempotent(session: DbSession) -> None:
    """It runs at every startup and every night, so a second run must not add a
    second set of weeks — nor a duplicate row for a Monday that already exists."""
    ensure_horizon(session, _at("2026-07-22T12:00"))
    first = _mondays(session)

    ensure_horizon(session, _at("2026-07-22T18:00"))

    assert _mondays(session) == first


def test_the_horizon_leaves_an_existing_week_untouched(session: DbSession) -> None:
    """The upcoming week is usually already solved or locked by the cron. The
    horizon must not reopen it — that would rewind the §3 lifecycle and make a
    published schedule editable again."""
    now = _at("2026-07-22T12:00")
    monday = upcoming_submittable_monday(now)
    session.add(Week(monday_date=monday, status=WeekStatus.LOCKED))
    session.commit()

    ensure_horizon(session, now)

    reloaded = session.scalar(select(Week).where(Week.monday_date == monday))
    assert reloaded is not None
    assert reloaded.status is WeekStatus.LOCKED


def test_the_deadlock_is_broken(session: DbSession) -> None:
    """The production failure, reproduced then fixed.

    One week exists, it is solved, its window has closed. Before the horizon this
    was terminal: no open week, and only a submission could create one. After it,
    a submittable week exists again without anyone having done anything.
    """
    now = _at("2026-07-22T12:00")
    stuck = upcoming_submittable_monday(now)
    session.add(Week(monday_date=stuck, status=WeekStatus.SOLVED))
    session.commit()
    assert not session.scalars(select(Week).where(Week.status == WeekStatus.OPEN)).all()

    ensure_horizon(session, now)

    open_weeks = session.scalars(select(Week).where(Week.status == WeekStatus.OPEN)).all()
    assert len(open_weeks) == HORIZON_WEEKS - 1
    assert all(w.monday_date > stuck for w in open_weeks)


# --- where the horizon starts ------------------------------------------------


def test_the_horizon_starts_at_the_next_submittable_monday(session: DbSession) -> None:
    """Mid-week, the current week's window closed last Sunday, so the horizon
    must start from the *next* Monday and never mint an unsubmittable week."""
    ensure_horizon(session, _at("2026-07-22T12:00"))  # a Wednesday

    assert _mondays(session)[0] == dt.date(2026, 7, 27)


def test_before_the_sunday_deadline_the_imminent_monday_still_counts() -> None:
    """§3.1: the window shuts at Sunday 17:00 Europe/Rome. At 14:00 that day the
    following Monday is still open for submissions, so it is where we start."""
    assert upcoming_submittable_monday(_at("2026-07-26T12:00")) == dt.date(2026, 7, 27)


def test_after_the_sunday_deadline_the_horizon_rolls_forward() -> None:
    """The boundary that a naive "next Monday" gets wrong: for the last hours of
    a Sunday the nearest Monday is already past submitting."""
    assert upcoming_submittable_monday(_at("2026-07-26T18:00")) == dt.date(2026, 8, 3)


def test_a_monday_is_never_its_own_horizon_start() -> None:
    """On a Monday the current week's window closed the evening before."""
    assert upcoming_submittable_monday(_at("2026-07-20T09:00")) == dt.date(2026, 7, 27)
