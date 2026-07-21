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
    """§3.1: constraints are editable only while the week is `open` AND its Sunday
    17:00 deadline has not passed. `now` defaults to now (UTC).

    The status is the primary gate: a `solved` or `locked` week refuses edits. That
    is what "Generate now marks the window closed early" (§3.2) means mechanically —
    once a solve runs, `run_solve` moves the week OPEN→SOLVED, so submissions stop
    immediately (ahead of the deadline if an admin generated early) and the solved
    schedule cannot be invalidated by a late edit. `solved_at is None` is kept as a
    belt-and-suspenders cross-check but is subsumed by the status transition.
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


# §3: "any future week with status open" is where a constraint may be submitted.
# Four keeps roughly a month reachable — enough that someone can enter a holiday
# before it is imminent, few enough that the week picker stays readable.
HORIZON_WEEKS = 4


def ensure_horizon(db: DbSession, now: dt.datetime, weeks: int = HORIZON_WEEKS) -> list[Week]:
    """Guarantee that the next `weeks` submittable Mondays exist as rows.

    Weeks used to be materialised only by the first submission for them, or by
    the solve job. That is a deadlock, and the deployment hit it: the cron
    created and solved the upcoming week, its window shut, and from then on the
    only week in existence was closed — so no constraint could be submitted for
    any week, and a submission was the one remaining thing that could have
    created another. The horizon breaks the cycle by never depending on user
    action to exist.

    Idempotent, so it is safe to run at every startup and every night: existing
    rows are returned untouched, whatever status they have since reached. It
    starts from the first Monday whose window is still open, so it never mints a
    week that could not be submitted to anyway.
    """
    monday = upcoming_submittable_monday(now)
    created: list[Week] = []
    for offset in range(weeks):
        week = get_or_create_week(db, monday + dt.timedelta(weeks=offset))
        created.append(week)
    return created


def upcoming_submittable_monday(now: dt.datetime) -> dt.date:
    """The first Monday whose submission window has not already closed (§3.1).

    Not simply "next Monday": the window shuts at Sunday 17:00 Europe/Rome, so
    for the last seven hours of a Sunday the nearest Monday is already beyond
    submitting and the horizon has to start from the one after it.
    """
    local = now.astimezone(_tz())
    monday = local.date() - dt.timedelta(days=local.weekday())
    while now >= window_deadline(monday):
        monday += dt.timedelta(weeks=1)
    return monday


def resolve_submittable_week(db: DbSession, monday_date: dt.date) -> Week:
    """The week `monday_date` names, ready to accept a constraint edit (§3.1).

    Raises 422 if `monday_date` is not a Monday, 409 if the window is closed —
    because the deadline has passed, or the week is no longer `open` (`solved` or
    `locked`, §3.2 "Generate now marks the window closed early"). A past week is
    refused *before* a row is created, so a closed submission never materialises a
    stray week.

    The `status is OPEN` gate makes this shared chokepoint agree with
    `is_submittable` (used by the DELETE path): once a solve runs, `run_solve`
    moves the week OPEN→SOLVED, so POST and DELETE both refuse the edit — a solved
    schedule (and any pending sacrifice proposal probed against its constraint set)
    cannot be invalidated by a late mutation. `solved_at is None` is kept as a
    belt-and-suspenders cross-check.
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
    if week.status is not WeekStatus.OPEN or week.solved_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_WEEK_CLOSED)
    return week
