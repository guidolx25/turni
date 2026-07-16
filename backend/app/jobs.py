"""Scheduled lifecycle jobs (spec §3.2/§3.3) — the logic, separate from the timer.

The weekly job that fires Sunday 17:00 Europe/Rome (§3) is split in two: this
module is the pure-ish *what* (find the upcoming week, solve, publish on success),
and `app.scheduler` is the *when* (the APScheduler cron trigger). Keeping them
apart means the whole behaviour is testable by calling `run_weekly_solve` with a
fixed `now`, without standing up a scheduler or waiting on a clock.

Auto-publish: a feasible scheduled solve publishes immediately (§3.2 → §3.3 in one
Sunday-17:00 automation). An INFEASIBLE one stops short of publishing and is left
for the §2.3 sacrifice flow (Increment E wires proposal creation into this branch);
the manual admin path (`/admin/solve`, `/admin/publish`) covers the same ground.
"""

from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.enums import WeekStatus
from app.publish_service import publish_week
from app.scheduling import get_or_create_week
from app.solve_service import run_solve
from app.solver import SolverResult, SolverStatus

logger = logging.getLogger(__name__)


def upcoming_monday(now: dt.datetime) -> dt.date:
    """The Monday of the week the Sunday-17:00 run is preparing — the first Monday
    strictly after `now`'s local date. From the Sunday it fires, that is tomorrow;
    computed generally so a manual/off-schedule call still targets the next week,
    never a week already under way."""
    local_date = now.astimezone(ZoneInfo(settings.tz)).date()
    days_ahead = (0 - local_date.weekday()) % 7 or 7  # 0 == Monday; never today
    return local_date + dt.timedelta(days=days_ahead)


def run_weekly_solve(db: DbSession, now: dt.datetime) -> SolverResult | None:
    """§3.2/§3.3: solve — and on success publish — the upcoming week.

    Idempotent: a week already locked (published) is skipped, so a re-fire never
    disturbs a live schedule. Returns the solve result, or None when skipped.
    """
    target = upcoming_monday(now)
    week = get_or_create_week(db, target)
    if week.status is WeekStatus.LOCKED:
        logger.info("weekly solve skipped: week %s already published", target)
        return None

    result = run_solve(db, week)
    if result.status is SolverStatus.INFEASIBLE:
        # §2.3: cannot publish an infeasible week. Increment E opens the sacrifice
        # flow here; until then the window is closed and an admin is alerted.
        logger.warning(
            "weekly solve INFEASIBLE for %s: %d blocking constraint(s) — sacrifice flow required",
            target,
            len(result.blocking_constraints),
        )
        return result

    publish_week(db, week, actor=None)  # system action (§6: null audit actor)
    logger.info("weekly solve published %s (%s)", target, result.status.value)
    return result
