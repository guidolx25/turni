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
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.backup import create_backup, prune_backups
from app.config import settings
from app.enums import SwapStatus, WeekStatus
from app.models import SwapRequest, User
from app.notifications import EVENT_WINDOW_CLOSING_24H, notify
from app.publish_service import publish_week
from app.sacrifice_service import open_sacrifice
from app.scheduling import ensure_horizon, get_or_create_week, is_submittable, window_deadline
from app.sessions import purge_expired_sessions
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


def run_window_reminder(db: DbSession, now: dt.datetime) -> int:
    """§10 `window_closing_24h`: tell the workers the submission window closes in 24 h.

    Fired Saturday 17:00 Europe/Rome (`app.scheduler`), exactly 24 h before the
    §3.1 Sunday-17:00 deadline for the same upcoming week `run_weekly_solve`
    targets — both derive it from `upcoming_monday`, so the reminder and the
    solve can never disagree about which week they mean. The deadline instant in
    the payload comes from `app.scheduling.window_deadline`, never recomputed
    here, so it is the same DST-correct instant the lifecycle enforces.

    **Audience: every active user.** Deliberately not "only those who have not
    submitted yet": §3.1 keeps constraints editable for as long as the week is
    open, so "24 h left" is actionable for someone who submitted on Monday and
    wants to change their mind. Per-user, exactly like `schedule_published` — so
    root receives it as a worker (he works shifts); §5 hides root from
    *role-based* fan-outs, which this is not.

    Skipped when the window is already shut — a `solved` week (an admin pressed
    "Generate now" early, §3.2) has nothing left to remind anyone about. Returns
    the number of users notified.
    """
    target = upcoming_monday(now)
    week = get_or_create_week(db, target)
    if not is_submittable(week, now):
        logger.info(
            "window reminder skipped: week %s is %s, window already closed",
            target,
            week.status.value,
        )
        return 0

    payload = {
        "week": week.monday_date.isoformat(),
        "deadline": window_deadline(week.monday_date).isoformat(),
    }
    recipients = db.scalars(select(User).where(User.active.is_(True))).all()
    for user in recipients:
        notify(db, user, EVENT_WINDOW_CLOSING_24H, payload)
    db.commit()
    logger.info("window reminder sent for %s to %d user(s)", target, len(recipients))
    return len(recipients)


def run_nightly_maintenance(db: DbSession, now: dt.datetime) -> Path | None:
    """§11: the nightly housekeeping run — SQLite backup, then session purge.

    Two chores, one fire, because both are "once a day, no user waiting":

    * **Backup** (§11: "nightly `sqlite3 .backup` to the volume, keep 14") — an
      online-API snapshot plus a prune to the newest `BACKUP_KEEP`. Audited with a
      NULL actor: §6 says a scheduled job has no human actor and there is
      deliberately no system user row, and "the backups ran" is exactly the kind
      of fact an operator later needs to establish from the log.
    * **Expired sessions** (§6 `sessions`: "expired rows are purged by the nightly
      job (§11)"). Expiry is already enforced on read, so this is housekeeping,
      not a security boundary — it just keeps the table from growing forever.

    A failed backup does not skip the purge, and neither raises: `create_backup`
    swallows and logs its own failures so APScheduler does not retire the job (see
    `app.backup`). The audit row records the outcome either way — including
    `"backup": null` for a failure, which is the log entry that lets someone
    notice backups have been silently failing for a week.

    Returns the snapshot path, or None if it could not be taken.
    """
    snapshot = create_backup(now)
    pruned = prune_backups(settings.backup_dir, settings.backup_keep) if snapshot else []
    purged = purge_expired_sessions(db, now=now)
    audit.record(
        db,
        None,  # §6: a scheduled job has no human actor
        audit.ACTION_BACKUP,
        "database",
        None,
        {
            "backup": str(snapshot) if snapshot is not None else None,
            "pruned": len(pruned),
            "sessions_purged": purged,
        },
    )
    # §3: keep the rolling submission horizon stocked. Last, because it must not
    # be skipped by a backup failure and must not itself abort the housekeeping —
    # it is the chore that keeps the app usable, not one that protects data.
    horizon = ensure_horizon(db, now)
    db.commit()
    logger.info(
        "nightly maintenance complete: backup=%s pruned=%d sessions_purged=%d horizon=%d",
        snapshot,
        len(pruned),
        purged,
        len(horizon),
    )
    return snapshot


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
