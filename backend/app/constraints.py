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
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db import utcnow
from app.enums import ConstraintKind, ConstraintSlot, Day
from app.models import Constraint, User, Week

# The am/pm pair a `full_day` write supersedes, and vice versa (§3.1).
_HALF_DAY_SLOTS = (ConstraintSlot.AM, ConstraintSlot.PM)


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

    Returns the surviving row. Commits once, so the supersede-then-write is atomic.
    """
    # §3.1 exclusion: a full_day write clears am/pm; an am/pm write clears full_day.
    superseded = _HALF_DAY_SLOTS if slot is ConstraintSlot.FULL_DAY else (ConstraintSlot.FULL_DAY,)
    for existing in _rows_for_day(db, user, week, day, superseded):
        db.delete(existing)

    row = _row_for_slot(db, user, week, day, slot)
    if row is None:
        row = Constraint(user_id=user.id, week_id=week.id, day=day, slot=slot, kind=kind, note=note)
        db.add(row)
    else:
        row.kind = kind
        row.note = note
        row.updated_at = utcnow()
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
