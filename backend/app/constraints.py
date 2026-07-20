"""Constraint submission logic (spec §3.1) — the upsert and its exclusion rule.

§3.1 makes a submission an **upsert** on `(user, week, day, slot)`, with one extra
rule the bare unique constraint cannot express: within a day, `full_day` and the
`am`/`pm` slots are mutually exclusive. Writing `full_day` clears any `am`/`pm`
rows for that day; writing `am`/`pm` clears a `full_day` row. That reconciliation
lives here, in one place, so the route handler stays a thin permission + shape
layer and the rule is unit-testable without HTTP.

Ownership is the caller's: every function operates on `user`'s own rows only
(§5 row 1). The admin "view all submissions" path (§5) is a separate read and
does not go through here.

One submission is accepted but cannot be *solved*: a HARD (H7) request on a
Sat/Sun, because H5 fixes the weekend as a template with no solver variables. The
row is still recorded — the request is legitimate — but §2.3 ("never resolve
silently") means it may not stop there, so creating one escalates to the visible
admins for a human decision against the template. See `_escalate_weekend_hard`.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.db import utcnow
from app.enums import ConstraintKind, ConstraintSlot, Day
from app.models import Constraint, User, Week
from app.notifications import EVENT_WEEKEND_HARD_ESCALATED, notify
from app.visibility import admin_recipients

logger = logging.getLogger(__name__)

# The am/pm pair a `full_day` write supersedes, and vice versa (§3.1).
_HALF_DAY_SLOTS = (ConstraintSlot.AM, ConstraintSlot.PM)

# H5 template days: the solver has no variables here, so a HARD request on one of
# them can only be resolved by a human (§2.3).
_TEMPLATE_DAYS = (Day.SAT, Day.SUN)


def list_own_constraints(db: DbSession, user: User, week: Week) -> list[Constraint]:
    """The caller's own constraints for `week` (§7 `GET /constraints?week=`),
    ordered for a stable response."""
    stmt = (
        select(Constraint)
        .where(Constraint.user_id == user.id, Constraint.week_id == week.id)
        .order_by(Constraint.day, Constraint.slot)
    )
    return list(db.scalars(stmt).all())


def upsert_constraint(
    db: DbSession,
    user: User,
    week: Week,
    day: Day,
    slot: ConstraintSlot,
    kind: ConstraintKind,
    note: str | None,
) -> Constraint:
    """Upsert one of the caller's constraints (§3.1), enforcing the full_day ↔
    am/pm exclusion within `(user, week, day)` before writing.

    A newly HARD request on an H5 template day also escalates to the admins — see
    `_escalate_weekend_hard`; it rides this transaction, so the row and the
    escalation land together or not at all.

    Returns the surviving row. Commits once, so the supersede-then-write is atomic.
    """
    # §3.1 exclusion: a full_day write clears am/pm; an am/pm write clears full_day.
    superseded = _HALF_DAY_SLOTS if slot is ConstraintSlot.FULL_DAY else (ConstraintSlot.FULL_DAY,)
    for existing in _rows_for_day(db, user, week, day, superseded):
        db.delete(existing)

    row = _row_for_slot(db, user, week, day, slot)
    # Captured before the write: escalate only when this request *becomes* hard, so
    # re-submitting an already-hard row (e.g. editing its note) does not re-notify.
    was_hard = row is not None and row.kind is ConstraintKind.HARD
    if row is None:
        row = Constraint(user_id=user.id, week_id=week.id, day=day, slot=slot, kind=kind, note=note)
        db.add(row)
    else:
        row.kind = kind
        row.note = note
        row.updated_at = utcnow()

    if kind is ConstraintKind.HARD and day in _TEMPLATE_DAYS and not was_hard:
        db.flush()  # assign an id for the audit/notification payload
        _escalate_weekend_hard(db, user, week, row)
    db.commit()
    return row


def delete_own_constraint(db: DbSession, user: User, constraint_id: int) -> Constraint | None:
    """Delete one of the caller's own constraints by id, or return None if it does
    not exist or belongs to someone else (§5 row 1 — no cross-user deletes).

    The window-open guard (§3.1) is applied by the caller against the row's week,
    since only the route has the request context to raise the right HTTP error.
    """
    row = db.get(Constraint, constraint_id)
    if row is None or row.user_id != user.id:
        return None
    return row


def _escalate_weekend_hard(db: DbSession, user: User, week: Week, row: Constraint) -> None:
    """§2.3/§10: hand a HARD request on an H5 template day to the admins.

    H5 makes Sat/Sun a fixed template, so the solver has no variable to bind this
    request to and skips it (see `app.solver.model`). Dropping it there and saying
    nothing would leave the worker believing an unavailability is honored while the
    template schedules them anyway — exactly the silent resolution §2.3 forbids. So
    the row stands (the request is legitimately recorded, §3.1) and a human is told.

    Role-based fan-out → `admin_recipients(db)` only, which excludes root via
    `visible_users_stmt` (§5). Does not commit: the caller owns the transaction.
    """
    payload = {
        "week": week.monday_date.isoformat(),
        "constraint_id": row.id,
        "user_id": user.id,
        "display_name": user.display_name,
        "day": row.day.value,
        "slot": row.slot.value,
        # Why this needs a human: H5's weekend template is not solved, so no
        # re-solve can honor the request.
        "reason": "weekend_template_fixed",
    }
    audit.record(db, user, audit.ACTION_ESCALATE, "constraint", row.id, payload)

    recipients = admin_recipients(db)
    if not recipients:
        # Never escalate into the void: with no visible admin nobody can reconcile
        # this against the template, so make the gap loud rather than silent (§2.3).
        logger.error(
            "Hard weekend constraint %s (user=%s %s %s, week %s) has no visible admin "
            "recipient; it cannot be reconciled against the H5 template.",
            row.id,
            user.display_name,
            row.day.value,
            row.slot.value,
            week.monday_date.isoformat(),
        )
        return
    for admin in recipients:
        notify(db, admin, EVENT_WEEKEND_HARD_ESCALATED, payload)


def _rows_for_day(
    db: DbSession,
    user: User,
    week: Week,
    day: Day,
    slots: tuple[ConstraintSlot, ...],
) -> list[Constraint]:
    stmt = select(Constraint).where(
        Constraint.user_id == user.id,
        Constraint.week_id == week.id,
        Constraint.day == day,
        Constraint.slot.in_(slots),
    )
    return list(db.scalars(stmt).all())


def _row_for_slot(
    db: DbSession, user: User, week: Week, day: Day, slot: ConstraintSlot
) -> Constraint | None:
    stmt = select(Constraint).where(
        Constraint.user_id == user.id,
        Constraint.week_id == week.id,
        Constraint.day == day,
        Constraint.slot == slot,
    )
    return db.scalar(stmt)
