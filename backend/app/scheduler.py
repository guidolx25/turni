"""APScheduler wiring (spec §3, §11) — the Sunday-17:00 Europe/Rome cron trigger.

Only the *timer* lives here; the job body is `app.jobs.run_weekly_solve`. The
trigger carries `timezone=Europe/Rome`, so APScheduler fires at 17:00 *local*
wall-clock and follows DST automatically — the same Europe/Rome discipline the
submission deadline uses (`app.scheduling.window_deadline`).

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
from app.jobs import run_weekly_solve

logger = logging.getLogger(__name__)

# §3: the window closes and the upcoming week is solved+published Sunday 17:00.
WINDOW_CLOSE_JOB_ID = "weekly_window_close_solve"
WINDOW_CLOSE_TRIGGER = CronTrigger(day_of_week="sun", hour=17, minute=0, timezone=settings.tz)


def _weekly_window_close() -> None:
    """Job entry point: one fresh session per fire, real current instant."""
    with SessionLocal() as db:
        run_weekly_solve(db, dt.datetime.now(dt.UTC))


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
    return scheduler
