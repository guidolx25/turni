"""§10 `window_closing_24h` — the Saturday-17:00 reminder cron (spec §3, §10).

Tested by calling `run_window_reminder` with a fixed `now`, the same way
`test_jobs` exercises the Sunday solve: the trigger's wiring is asserted
separately, so no test here waits on a clock.

The load-bearing claims: it targets the same week the Sunday solve will,
it fires exactly 24 h (wall-clock) before the §3.1 deadline across DST, it
reaches every active worker (root included, as a worker), and it stays quiet
once the window is shut.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.email import NullTransport
from app.enums import WeekStatus
from app.jobs import run_window_reminder, upcoming_monday
from app.models import Notification
from app.notifications import EVENT_WINDOW_CLOSING_24H
from app.scheduler import WINDOW_REMINDER_JOB_ID, WINDOW_REMINDER_TRIGGER, build_scheduler
from app.scheduling import get_or_create_week, window_deadline
from tests.factories import create_full_roster, create_user

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase5

ROME = ZoneInfo("Europe/Rome")

# The Saturday the reminder fires (17:00 Rome) for the 2026-07-13 week.
FIRE_SATURDAY = dt.datetime(2026, 7, 11, 17, 0, tzinfo=ROME)
TARGET_MONDAY = dt.date(2026, 7, 13)


def notifications_for(db: DbSession) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification).where(Notification.event_type == EVENT_WINDOW_CLOSING_24H)
        ).all()
    )


# --- trigger wiring ---------------------------------------------------------


def test_trigger_is_saturday_1700_rome() -> None:
    """§10: "reminder cron Sat 17:00" — 24 h before §3.1's Sunday 17:00."""
    fields = {field.name: str(field) for field in WINDOW_REMINDER_TRIGGER.fields}
    assert fields["day_of_week"] == "sat"
    assert fields["hour"] == "17"
    assert fields["minute"] == "0"
    assert str(WINDOW_REMINDER_TRIGGER.timezone) == "Europe/Rome"


def test_trigger_follows_dst_like_the_window_close() -> None:
    """Rome wall-clock, not a fixed UTC offset: 15:00 UTC in summer, 16:00 in
    winter — exactly the discipline `window_deadline` uses (§3)."""
    summer = WINDOW_REMINDER_TRIGGER.get_next_fire_time(
        None, dt.datetime(2026, 7, 6, 12, 0, tzinfo=ROME)
    )
    winter = WINDOW_REMINDER_TRIGGER.get_next_fire_time(
        None, dt.datetime(2026, 12, 7, 12, 0, tzinfo=ROME)
    )
    assert summer is not None and winter is not None
    assert summer.astimezone(dt.UTC).hour == 15
    assert winter.astimezone(dt.UTC).hour == 16


def test_job_is_registered() -> None:
    scheduler = build_scheduler()
    assert scheduler.get_job(WINDOW_REMINDER_JOB_ID) is not None


# --- target week ------------------------------------------------------------


def test_targets_the_same_week_the_sunday_solve_will(session: DbSession) -> None:
    """Both derive the week from `upcoming_monday`, so they cannot disagree."""
    assert upcoming_monday(FIRE_SATURDAY) == TARGET_MONDAY

    create_user(session, "pasha")
    run_window_reminder(session, FIRE_SATURDAY)

    rows = notifications_for(session)
    assert rows[0].payload is not None
    assert rows[0].payload["week"] == TARGET_MONDAY.isoformat()


def test_payload_carries_the_lifecycle_deadline(session: DbSession) -> None:
    """The instant in the payload is `window_deadline`'s, never recomputed —
    so the countdown a worker sees is the one the lifecycle enforces (§3.1)."""
    create_user(session, "pasha")
    run_window_reminder(session, FIRE_SATURDAY)

    rows = notifications_for(session)
    assert rows[0].payload is not None
    assert rows[0].payload["deadline"] == window_deadline(TARGET_MONDAY).isoformat()


def test_reminder_precedes_the_deadline_by_24h_in_winter(session: DbSession) -> None:
    """Across the October change the two crons stay 24 h apart in Rome wall
    clock, which is what "you have 24 hours" means to the reader."""
    winter_saturday = dt.datetime(2026, 12, 5, 17, 0, tzinfo=ROME)
    create_user(session, "pasha")

    run_window_reminder(session, winter_saturday)

    rows = notifications_for(session)
    assert rows[0].payload is not None
    deadline = dt.datetime.fromisoformat(str(rows[0].payload["deadline"]))
    assert deadline - winter_saturday == dt.timedelta(hours=24)


# --- audience ---------------------------------------------------------------


def test_reaches_every_active_worker_including_root(session: DbSession) -> None:
    """Per-user, not a role fan-out: §5 hides root from role-based recipient
    lists, and root (Matteo) works shifts, so he gets his own reminder — the
    same rule `schedule_published` follows."""
    roster = create_full_roster(session)

    count = run_window_reminder(session, FIRE_SATURDAY)

    recipients = {row.user_id for row in notifications_for(session)}
    assert recipients == {user.id for user in roster.values()}
    assert roster["matteo"].id in recipients
    assert count == len(roster)


def test_skips_deactivated_users(session: DbSession) -> None:
    """§5: a deactivated account is not a recipient."""
    active = create_user(session, "pasha")
    create_user(session, "ghost", active=False)

    run_window_reminder(session, FIRE_SATURDAY)

    assert {row.user_id for row in notifications_for(session)} == {active.id}


def test_sends_email_to_opted_in_workers(session: DbSession, email_outbox: NullTransport) -> None:
    """§10 Channel 2 rides the same `notify()` call — the job never talks to a
    channel directly."""
    create_user(session, "pasha", email="pasha@example.com")
    create_user(session, "amir", email=None)

    run_window_reminder(session, FIRE_SATURDAY)

    assert [message.to for message in email_outbox.sent] == ["pasha@example.com"]


# --- window state -----------------------------------------------------------


def test_silent_once_the_window_is_closed_early(session: DbSession) -> None:
    """§3.2: an admin "Generate now" shuts the window ahead of the deadline —
    there is nothing left to remind anyone about."""
    create_user(session, "pasha")
    week = get_or_create_week(session, TARGET_MONDAY)
    week.status = WeekStatus.SOLVED
    session.commit()

    assert run_window_reminder(session, FIRE_SATURDAY) == 0
    assert notifications_for(session) == []


def test_silent_after_the_deadline_has_passed(session: DbSession) -> None:
    """A misfired catch-up run after Sunday 17:00 must not send "24 h left".

    `upcoming_monday` still names 2026-07-13 from the Sunday evening (the next
    Monday is tomorrow), but that week's window shut an hour earlier — so the
    `is_submittable` gate, not the target-week arithmetic, is what keeps a late
    fire from telling workers they have time they no longer have.
    """
    create_user(session, "pasha")
    after_deadline = dt.datetime(2026, 7, 12, 18, 0, tzinfo=ROME)
    assert upcoming_monday(after_deadline) == TARGET_MONDAY

    assert run_window_reminder(session, after_deadline) == 0
    assert notifications_for(session) == []
