"""Weekly window-close job (spec §3.2/§3.3) — logic tested without the timer.

`run_weekly_solve` is exercised directly with a fixed `now`, so the whole
solve-then-publish behaviour is verified without standing up APScheduler. The
DST-correctness of the deadline itself lives in `test_scheduling`; here we check
target-week selection, auto-publish, the infeasible short-circuit, and idempotence.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.enums import ConstraintKind, ConstraintSlot, Day, SacrificeStatus, WeekStatus
from app.jobs import run_weekly_solve, upcoming_monday
from app.models import Constraint, Notification, SacrificeProposal, Week
from app.notifications import EVENT_SACRIFICE_ESCALATED
from app.sacrifice_service import _create_proposal, accept_sacrifice
from app.scheduler import WINDOW_CLOSE_TRIGGER, build_scheduler
from app.scheduling import get_or_create_week
from app.solve_service import run_solve
from tests.factories import create_full_roster

ROME = ZoneInfo("Europe/Rome")

# The Sunday the cron fires (17:00 Rome) before the 2026-07-13 week.
_FIRE_SUNDAY = dt.datetime(2026, 7, 12, 17, 0, tzinfo=ROME)
_TARGET_MONDAY = dt.date(2026, 7, 13)


# --- target selection -------------------------------------------------------


def test_upcoming_monday_from_the_firing_sunday() -> None:
    """The Sunday-17:00 fire targets the very next day's Monday."""
    assert upcoming_monday(_FIRE_SUNDAY) == _TARGET_MONDAY


def test_upcoming_monday_is_always_in_the_future() -> None:
    """Even called on a Monday, it targets NEXT week — never the week under way."""
    a_monday = dt.datetime(2026, 7, 13, 9, 0, tzinfo=ROME)
    assert upcoming_monday(a_monday) == dt.date(2026, 7, 20)


def test_upcoming_monday_uses_rome_local_date() -> None:
    """A UTC instant just before Rome midnight resolves to the Rome date. 22:30
    UTC on Sun is 00:30 Mon in CEST — still targets the following Monday."""
    late_utc = dt.datetime(2026, 7, 12, 22, 30, tzinfo=dt.UTC)  # 00:30 Mon in Rome
    assert upcoming_monday(late_utc) == dt.date(2026, 7, 20)


# --- solve + auto-publish ---------------------------------------------------


def test_weekly_solve_publishes_the_upcoming_week(session: DbSession) -> None:
    create_full_roster(session)
    result = run_weekly_solve(session, _FIRE_SUNDAY)
    assert result is not None and result.status.value in ("optimal", "feasible")

    week = session.scalar(select(Week).where(Week.monday_date == _TARGET_MONDAY))
    assert week is not None and week.status is WeekStatus.LOCKED  # auto-published
    assert session.scalars(select(Notification)).all()  # fan-out happened


def test_weekly_solve_infeasible_does_not_publish(session: DbSession) -> None:
    """An INFEASIBLE upcoming week is solved (window closed) but not published —
    it awaits the §2.3 sacrifice flow."""
    roster = create_full_roster(session)
    week = get_or_create_week(session, _TARGET_MONDAY)
    for name in ("matteo", "francesco", "mattia"):
        session.add(
            Constraint(
                user_id=roster[name].id,
                week_id=week.id,
                day=Day.MON,
                slot=ConstraintSlot.FULL_DAY,
                kind=ConstraintKind.HARD,
            )
        )
    session.commit()

    result = run_weekly_solve(session, _FIRE_SUNDAY)
    assert result is not None and result.status.value == "infeasible"
    session.refresh(week)
    assert week.status is WeekStatus.SOLVED  # parked, not published (§3.3)
    # No schedule_published fan-out; the §2.3 flow may still notify (proposal or
    # escalation), but nobody is told a schedule went live.
    published = session.scalars(
        select(Notification).where(Notification.event_type == "schedule_published")
    ).all()
    assert published == []


def test_weekly_solve_feasible_locks_atomically_with_fanout(session: DbSession) -> None:
    """§3.3 cron-atomic path: a feasible scheduled solve on an OPEN week goes
    straight to LOCKED (solve+publish in one automation) and fans out
    `schedule_published` to every active user (incl. root, per project convention)."""
    roster = create_full_roster(session)
    result = run_weekly_solve(session, _FIRE_SUNDAY)
    assert result is not None and result.status.value in ("optimal", "feasible")

    week = session.scalar(select(Week).where(Week.monday_date == _TARGET_MONDAY))
    assert week is not None and week.status is WeekStatus.LOCKED

    published = session.scalars(
        select(Notification).where(Notification.event_type == "schedule_published")
    ).all()
    assert {n.user_id for n in published} == {u.id for u in roster.values()}


def _parked_week_with_pending_proposal(session: DbSession, roster: dict):
    """A week parked in `solved`, unpublished, carrying one PENDING §2.3 proposal.

    `run_solve` (not the cron job) does the solving, so the feasible week parks in
    `solved` without publishing — exactly the state a cron-parked week sits in
    while its §2.3 conversation is open. The proposal is seeded through
    `sacrifice_service._create_proposal` because `open_sacrifice`'s probe can no
    longer succeed for any input (see `tests/test_sacrifice_api.py`), which makes
    the propose branch unreachable via the cron path.
    """
    week = get_or_create_week(session, _TARGET_MONDAY)
    run_solve(session, week)
    proposal = _create_proposal(
        session, week, roster["pasha"].id, Day.THU, conflict_note="Pasha thu full_day."
    )
    return week, proposal


def test_accepting_a_sacrifice_auto_publishes_the_parked_week(session: DbSession) -> None:
    """§3.3 sacrifice-pending path: a week parked in `solved` with a pending
    proposal has published nothing; accepting the sacrifice re-solves with the free
    day pinned and AUTO-publishes → LOCKED, fanning out `schedule_published` to
    every active user."""
    roster = create_full_roster(session)
    week, proposal = _parked_week_with_pending_proposal(session, roster)

    session.refresh(week)
    assert week.status is WeekStatus.SOLVED  # parked, awaiting the §2.3 resolution
    assert proposal.status is SacrificeStatus.PENDING
    assert (
        session.scalars(
            select(Notification).where(Notification.event_type == "schedule_published")
        ).all()
        == []
    )  # nothing published while parked

    accept_sacrifice(session, proposal, actor=roster["pasha"])
    session.refresh(week)
    assert week.status is WeekStatus.LOCKED  # auto-published on resolution

    published = session.scalars(
        select(Notification).where(Notification.event_type == "schedule_published")
    ).all()
    assert {n.user_id for n in published} == {u.id for u in roster.values()}


def test_weekly_solve_refire_on_parked_solved_is_idempotent(session: DbSession) -> None:
    """A cron re-fire over a `solved` week parked with a pending proposal does NOT
    re-solve, does NOT open a duplicate proposal, and does NOT publish — it is
    skipped (returns None), leaving the parked week untouched for the §2.3 flow."""
    roster = create_full_roster(session)
    week, _proposal = _parked_week_with_pending_proposal(session, roster)
    session.refresh(week)
    assert week.status is WeekStatus.SOLVED
    assert len(session.scalars(select(SacrificeProposal)).all()) == 1

    again = run_weekly_solve(session, _FIRE_SUNDAY)  # re-fire on the parked week
    assert again is None  # skipped: not re-solved
    session.refresh(week)
    assert week.status is WeekStatus.SOLVED  # unchanged
    assert len(session.scalars(select(SacrificeProposal)).all()) == 1  # no duplicate
    assert (
        session.scalars(
            select(Notification).where(Notification.event_type == "schedule_published")
        ).all()
        == []
    )


def test_weekly_solve_refire_on_an_escalated_infeasible_week_is_idempotent(
    session: DbSession,
) -> None:
    """§2.3/§3.3: a cron solve that went INFEASIBLE and escalated leaves the week
    parked in `solved`. A re-fire must not re-solve it, re-escalate, or publish —
    the admin owns it now."""
    roster = create_full_roster(session)
    week = get_or_create_week(session, _TARGET_MONDAY)
    for name in ("matteo", "francesco", "mattia"):
        session.add(
            Constraint(
                user_id=roster[name].id,
                week_id=week.id,
                day=Day.MON,
                slot=ConstraintSlot.FULL_DAY,
                kind=ConstraintKind.HARD,
            )
        )
    session.commit()

    first = run_weekly_solve(session, _FIRE_SUNDAY)
    assert first is not None and first.status.value == "infeasible"
    escalations_after_first = len(
        session.scalars(
            select(Notification).where(Notification.event_type == EVENT_SACRIFICE_ESCALATED)
        ).all()
    )
    assert escalations_after_first == 1  # the visible admin, once

    assert run_weekly_solve(session, _FIRE_SUNDAY) is None  # skipped
    session.refresh(week)
    assert week.status is WeekStatus.SOLVED
    assert (
        len(
            session.scalars(
                select(Notification).where(Notification.event_type == EVENT_SACRIFICE_ESCALATED)
            ).all()
        )
        == escalations_after_first
    )  # no duplicate escalation
    assert (
        session.scalars(
            select(Notification).where(Notification.event_type == "schedule_published")
        ).all()
        == []
    )


def test_weekly_solve_skips_already_published_week(session: DbSession) -> None:
    """Idempotent: a re-fire over an already-locked week does nothing (returns None)."""
    create_full_roster(session)
    run_weekly_solve(session, _FIRE_SUNDAY)  # publishes
    again = run_weekly_solve(session, _FIRE_SUNDAY)
    assert again is None


# --- trigger configuration (§3: Sunday 17:00 Europe/Rome) -------------------


def test_trigger_is_sunday_1700_europe_rome() -> None:
    fields = {f.name: str(f) for f in WINDOW_CLOSE_TRIGGER.fields}
    assert fields["day_of_week"] == "sun"
    assert fields["hour"] == "17"
    assert fields["minute"] == "0"
    assert str(WINDOW_CLOSE_TRIGGER.timezone) == "Europe/Rome"


def test_build_scheduler_registers_the_job() -> None:
    # Built but not started (main starts it in the lifespan), so no shutdown here.
    scheduler = build_scheduler()
    assert scheduler.get_job("weekly_window_close_solve") is not None
