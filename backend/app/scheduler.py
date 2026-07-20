"""APScheduler wiring (spec §3, §4, §11) — the cron triggers.

Only the *timers* live here; the job bodies are in `app.jobs`
(`run_weekly_solve` for the Sunday-17:00 window close, `expire_stale_swaps` for
the hourly §4 swap expiry). The weekly trigger carries `timezone=Europe/Rome`,
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
from app.jobs import expire_stale_swaps, run_weekly_solve

logger = logging.getLogger(__name__)

# §3: the window closes and the upcoming week is solved+published Sunday 17:00.
WINDOW_CLOSE_JOB_ID = "weekly_window_close_solve"
WINDOW_CLOSE_TRIGGER = CronTrigger(day_of_week="sun", hour=17, minute=0, timezone=settings.tz)

# §4: pending swaps expire 48 h after creation. Hourly sweep — the deadline has
# hour-level granularity, and the lazy check in `app.swap_service` catches any
# request acted on between fires, so a finer cron would buy nothing.
SWAP_EXPIRY_JOB_ID = "hourly_swap_expiry"
SWAP_EXPIRY_TRIGGER = CronTrigger(minute=0, timezone=settings.tz)


def _weekly_window_close() -> None:
    """Job entry point: one fresh session per fire, real current instant."""
    with SessionLocal() as db:
        run_weekly_solve(db, dt.datetime.now(dt.UTC))


def _hourly_swap_expiry() -> None:
    """Job entry point: one fresh session per fire, real current instant."""
    with SessionLocal() as db:
        expire_stale_swaps(db, dt.datetime.now(dt.UTC))


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
        _hourly_swap_expiry,
        trigger=SWAP_EXPIRY_TRIGGER,
        id=SWAP_EXPIRY_JOB_ID,
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    return scheduler
