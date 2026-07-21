"""APScheduler wiring (spec §3, §4, §11) — the cron triggers.

Only the *timers* live here; the job bodies are in `app.jobs`
(`run_weekly_solve` for the Sunday-17:00 window close, `run_window_reminder` for
the §10 Saturday-17:00 `window_closing_24h` reminder, `expire_stale_swaps` for
the hourly §4 swap expiry). The weekly triggers carry `timezone=Europe/Rome`,
so APScheduler fires at 17:00 *local* wall-clock and follows DST automatically —
the same Europe/Rome discipline the submission deadline uses
(`app.scheduling.window_deadline`).

The scheduler is created but not started here; `app.main` starts it in the app
lifespan and shuts it down on exit, so importing this module (and the app, and
the test suite) never spins up a background thread.
"""

from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db import SessionLocal
from app.jobs import (
    expire_stale_swaps,
    run_nightly_maintenance,
    run_weekly_solve,
    run_window_reminder,
)

logger = logging.getLogger(__name__)

# §3: the window closes and the upcoming week is solved+published Sunday 17:00.
WINDOW_CLOSE_JOB_ID = "weekly_window_close_solve"
WINDOW_CLOSE_TRIGGER = CronTrigger(day_of_week="sun", hour=17, minute=0, timezone=settings.tz)

# §10: the `window_closing_24h` reminder cron — Saturday 17:00, i.e. 24 h before
# the §3.1 deadline above. Same `timezone=settings.tz`, so the two stay exactly
# 24 h apart across a DST boundary as *wall clock*, which is what "24 h left"
# means to a worker reading it.
WINDOW_REMINDER_JOB_ID = "weekly_window_reminder"
WINDOW_REMINDER_TRIGGER = CronTrigger(day_of_week="sat", hour=17, minute=0, timezone=settings.tz)

# §4: pending swaps expire 48 h after creation. Hourly sweep — the deadline has
# hour-level granularity, and the lazy check in `app.swap_service` catches any
# request acted on between fires, so a finer cron would buy nothing.
SWAP_EXPIRY_JOB_ID = "hourly_swap_expiry"
SWAP_EXPIRY_TRIGGER = CronTrigger(minute=0, timezone=settings.tz)

# §11: nightly SQLite backup (keep 14) plus the §6 expired-session purge. Same
# `timezone=settings.tz` as the rest, so it stays at the same local hour across a
# DST change — and on the spring-forward night, when 02:00–03:00 local does not
# exist, an hour that does.
NIGHTLY_MAINTENANCE_JOB_ID = "nightly_maintenance"
NIGHTLY_MAINTENANCE_TRIGGER = CronTrigger(
    hour=settings.backup_hour, minute=settings.backup_minute, timezone=settings.tz
)


def _weekly_window_close() -> None:
    """Job entry point: one fresh session per fire, real current instant."""
    with SessionLocal() as db:
        run_weekly_solve(db, dt.datetime.now(dt.UTC))


def _weekly_window_reminder() -> None:
    """Job entry point: one fresh session per fire, real current instant."""
    with SessionLocal() as db:
        run_window_reminder(db, dt.datetime.now(dt.UTC))


def _hourly_swap_expiry() -> None:
    """Job entry point: one fresh session per fire, real current instant."""
    with SessionLocal() as db:
        expire_stale_swaps(db, dt.datetime.now(dt.UTC))


def _nightly_maintenance() -> None:
    """Job entry point: one fresh session per fire, real current instant."""
    with SessionLocal() as db:
        run_nightly_maintenance(db, dt.datetime.now(dt.UTC))


def build_scheduler() -> BackgroundScheduler:
    """A scheduler with the weekly window-close job registered (not started).

    `coalesce=True` + `misfire_grace_time`: if the process was down over 17:00, a
    single catch-up run fires rather than a burst, and a slightly late fire still
    counts (the week is identified by date, not by the exact instant)."""
    scheduler = BackgroundScheduler(timezone=settings.tz)
    scheduler.add_job(
        _weekly_window_close,
        trigger=WINDOW_CLOSE_TRIGGER,
        id=WINDOW_CLOSE_JOB_ID,
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    scheduler.add_job(
        _weekly_window_reminder,
        trigger=WINDOW_REMINDER_TRIGGER,
        id=WINDOW_REMINDER_JOB_ID,
        coalesce=True,
        # Shorter grace than the solve: a reminder that arrives hours late has
        # eaten the notice it exists to give, and a reminder fired after the
        # Sunday deadline would be actively misleading. `run_window_reminder`
        # re-checks the window anyway, so a late fire is a no-op, not a lie.
        misfire_grace_time=3600,
        replace_existing=True,
    )
    scheduler.add_job(
        _hourly_swap_expiry,
        trigger=SWAP_EXPIRY_TRIGGER,
        id=SWAP_EXPIRY_JOB_ID,
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    scheduler.add_job(
        _nightly_maintenance,
        trigger=NIGHTLY_MAINTENANCE_TRIGGER,
        id=NIGHTLY_MAINTENANCE_JOB_ID,
        coalesce=True,
        # Generous grace: a backup that runs late is still a backup, and a night
        # the process was briefly down must not become a night with no snapshot.
        misfire_grace_time=6 * 3600,
        replace_existing=True,
    )
    return scheduler
