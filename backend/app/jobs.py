"""Scheduled lifecycle jobs (spec §3.2/§3.3) — the logic, separate from the timer.

The weekly job that fires Sunday 17:00 Europe/Rome (§3) is split in two: this
module is the pure-ish *what* (find the upcoming week, solve, publish on success),
and `app.scheduler` is the *when* (the APScheduler cron trigger). Keeping them
apart means the whole behaviour is testable by calling `run_weekly_solve` with a
fixed `now`, without standing up a scheduler or waiting on a clock.

Auto-publish: a feasible scheduled solve publishes immediately — solve+publish in
one Sunday-17:00 automation (§3.2 → §3.3) — *unless* a sacrifice is pending. An
INFEASIBLE one stops short of publishing, opens the §2.3 sacrifice flow, and leaves
the week parked in `solved` for resolution; the manual admin path (`/admin/solve`,
`/admin/publish`) covers the same ground.
"""

from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.enums import SwapStatus, WeekStatus
from app.models import SwapRequest
from app.publish_service import publish_week
from app.sacrifice_service import open_sacrifice
from app.scheduling import get_or_create_week
from app.solve_service import run_solve
from app.solver import SolverResult, SolverStatus
from app.swap_service import SWAP_TTL, expire_swap

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
    """§3.2/§3.3: solve — and on success atomically publish — the upcoming week,
    unless a sacrifice is pending.

    Idempotent: only an `open` week is acted on. A week already `solved` (manually
    generated and awaiting review, or parked with a pending/escalated sacrifice)
    must NOT be re-solved or auto-published by a cron re-fire; a `locked` week is
    done. Both are skipped, so a re-fire never disturbs a schedule mid-lifecycle.
    Returns the solve result, or None when skipped.
    """
    target = upcoming_monday(now)
    week = get_or_create_week(db, target)
    if week.status is not WeekStatus.OPEN:
        logger.info("weekly solve skipped: week %s is %s, not open", target, week.status.value)
        return None

    result = run_solve(db, week)  # OPEN → SOLVED (§3.2)
    if result.status is SolverStatus.INFEASIBLE:
        # §2.3: cannot publish an infeasible week — open the sacrifice flow (probe
        # → propose to a core worker, or escalate to the admin). The week stays
        # parked in `solved`; never silent, never auto-published with a conflict.
        logger.warning(
            "weekly solve INFEASIBLE for %s: %d blocking constraint(s) — opening sacrifice flow",
            target,
            len(result.blocking_constraints),
        )
        open_sacrifice(db, week, result)
        return result

    # Feasible: atomic solve+publish (SOLVED → LOCKED) — no sacrifice is pending.
    publish_week(db, week, actor=None)  # system action (§6: null audit actor)
    logger.info("weekly solve published %s (%s)", target, result.status.value)
    return result


def expire_stale_swaps(db: DbSession, now: dt.datetime) -> int:
    """§4: sweep `pending` swap requests older than 48 h into `expired`.

    The scheduled half of the expiry (hourly cron, `app.scheduler`); the lazy
    half lives in `app.swap_service`, which expires an overdue request the moment
    someone tries to act on or list it — same `expire_swap` transition either
    way, so both paths audit identically (NULL actor: a timeout has no human
    actor, §6) and neither notifies (§10's event list names no expiry event).
    Idempotent: an already-expired row no longer matches the filter. Returns the
    number of requests expired.
    """
    stale = db.scalars(
        select(SwapRequest).where(
            SwapRequest.status == SwapStatus.PENDING,
            SwapRequest.created_at <= now - SWAP_TTL,
        )
    ).all()
    for swap in stale:
        expire_swap(db, swap, now)
    if stale:
        db.commit()
        logger.info("expired %d stale swap request(s)", len(stale))
    return len(stale)
