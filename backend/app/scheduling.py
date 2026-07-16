"""Weekly-lifecycle time logic (spec §3) — the Europe/Rome window boundary.

§3 runs the whole lifecycle in Europe/Rome but the DB stores UTC (project
convention, enforced by `app.db.UtcDateTime`). The one place that conversion is
subtle is the submission deadline: "Sunday 17:00 before the week starts" is a
*local* wall-clock instant whose UTC offset changes with DST (15:00 UTC in
summer, 16:00 UTC in winter). This module is the single source of that arithmetic
so no endpoint or cron job open-codes a timezone conversion.

`window_deadline` is pure; `get_or_create_week` / `resolve_submittable_week` are
the DB-touching helpers the constraint routes share so the "editable only while
open" rule (§3.1) is enforced in exactly one place.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import utcnow
from app.enums import WeekStatus
from app.models import Week

# §3.1: the submission window closes Sunday 17:00 Europe/Rome before the week.
WINDOW_CLOSE_HOUR = 17

# Machine codes (§9 keeps user-visible strings in the i18n dictionaries).
ERROR_NOT_MONDAY = "week_not_monday"
ERROR_WEEK_CLOSED = "week_closed"


def _tz() -> ZoneInfo:
    """The scheduling timezone (Europe/Rome; §3). Read from settings so a test or
    deployment can pin it, never hardcoded at a call site."""
    return ZoneInfo(settings.tz)


def ensure_monday(monday_date: dt.date) -> None:
    """A week is identified by its Monday (§6 `weeks.monday_date`). Reject any
    other weekday before it can become a mislabelled week row."""
    if monday_date.weekday() != 0:  # Monday == 0
        raise ValueError(f"week must be identified by a Monday, got {monday_date:%A} {monday_date}")


def window_deadline(monday_date: dt.date) -> dt.datetime:
    """§3.1: the instant this week's submission window closes — Sunday 17:00
    Europe/Rome immediately before `monday_date` — as tz-aware UTC.

    Pure. DST-correct: 17:00 never falls in the spring-forward gap, so the local
    time is unambiguous; `astimezone` then applies the right offset for the season.
    """
    ensure_monday(monday_date)
    sunday = monday_date - dt.timedelta(days=1)
    local = dt.datetime.combine(sunday, dt.time(WINDOW_CLOSE_HOUR), tzinfo=_tz())
    return local.astimezone(dt.UTC)


def is_submittable(week: Week, now: dt.datetime | None = None) -> bool:
    """§3.1: constraints are editable only while the week is open, no solve has
    run, AND its Sunday 17:00 deadline has not passed. `now` defaults to now (UTC).

    The `solved_at` guard is what "Generate now marks the window closed early"
    (§3.2) means mechanically: once a solve runs, submissions stop immediately —
    ahead of the deadline if an admin generated early — so the solved schedule
    cannot be invalidated by a late edit.
    """
    moment = now or utcnow()
    return (
        week.status is WeekStatus.OPEN
        and week.solved_at is None
        and moment < window_deadline(week.monday_date)
    )


def get_or_create_week(db: DbSession, monday_date: dt.date) -> Week:
    """Fetch the §6 `weeks` row for `monday_date`, creating an OPEN one if absent.

    Weeks are created lazily — the first constraint submitted for a future week
    materialises it. Callers that must not create a past week gate on
    `resolve_submittable_week` instead.
    """
    ensure_monday(monday_date)
    week = db.scalar(select(Week).where(Week.monday_date == monday_date))
    if week is None:
        week = Week(monday_date=monday_date, status=WeekStatus.OPEN)
        db.add(week)
        db.commit()
    return week


def resolve_submittable_week(db: DbSession, monday_date: dt.date) -> Week:
    """The week `monday_date` names, ready to accept a constraint edit (§3.1).

    Raises 422 if `monday_date` is not a Monday, 409 if the window is closed —
    either because the deadline has passed or the week is already locked. A past
    week is refused *before* a row is created, so a closed submission never
    materialises a stray week.
    """
    try:
        ensure_monday(monday_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERROR_NOT_MONDAY
        ) from exc

    # Refuse a past/closed window before get_or_create can persist it.
    if utcnow() >= window_deadline(monday_date):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_WEEK_CLOSED)

    week = get_or_create_week(db, monday_date)
    if week.status is not WeekStatus.OPEN:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_WEEK_CLOSED)
    return week
