"""The §4 swap state machine — post-lock schedule changes by mutual consent.

pending → accepted → applied (atomic) with `REQUIRE_ADMIN_APPROVAL` off;
pending → accepted → pending_admin (parked, no application) with it on;
pending → rejected on refusal; pending → expired 48 h after creation (§4).

Validation runs FULLY at creation AND AGAIN at acceptance (§4: the schedule may
have changed in between — another swap, an override). Both paths go through the
same `validate_swap`, which checks, in order:

- both assignment rows exist, are held by the named parties, share one week, and
  that week is LOCKED (§3.4: swaps are the post-lock instrument — before publish
  the schedule is not even visible, let alone tradeable);
- H5: a swap touching a weekend row is legal only bagnino↔bagnino — the weekend
  is a fixed template "modifiable only via post-lock swap (bagnino↔bagnino) or
  admin override" (§2.1 H5), so any spiaggino weekend row is refused;
- role validity (§4): each party's WORKER role must be able to hold the row they
  would take — bagnino↔bagnino, spiaggino↔spiaggino, the jolly matches either.
  By role, never by name;
- H2–H4 for BOTH parties against the hypothetical post-swap assignment set:
  no two roles in one (day, slot) (H2), no core worker doubled on a weekday
  (H4 — the jolly may double, H6), and each core party still holding exactly one
  free weekday inside their legal H3 domain — Mon–Thu, extended by the week's
  accepted §2.3 sacrifice grant (the v1.6 grant of record, read through the same
  `accepted_sacrifice_grants` helper every solve uses).

Application is atomic (§4): one transaction exchanges the two rows' holders,
stamps `source = swap`, resolves the request, writes ONE audit row and fans out
`swap_accepted` to both parties and the visible admins (root excluded via
`app.visibility.admin_recipients`, §5 — never an ad-hoc recipient query).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any, NamedTuple, Protocol

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.config import settings
from app.db import utcnow
from app.enums import (
    AssignmentRole,
    AssignmentSource,
    Day,
    SwapStatus,
    UserRole,
    WeekStatus,
)
from app.models import Assignment, SwapRequest, User, Week
from app.notifications import (
    EVENT_SWAP_ACCEPTED,
    EVENT_SWAP_REJECTED,
    EVENT_SWAP_REQUESTED,
    notify,
)
from app.publish_service import write_solver_state
from app.solve_service import accepted_sacrifice_grants
from app.solver import FREE_DAYS, SOLVER_DAYS
from app.visibility import admin_recipients

# §4: an unanswered request expires 48 h after creation.
SWAP_TTL = dt.timedelta(hours=48)

_WEEKEND_DAYS = frozenset((Day.SAT, Day.SUN))

# Stable machine codes (§9 keeps user-visible strings in the i18n dictionaries).
ERROR_SWAP_NOT_FOUND = "swap_not_found"  # 404: missing OR not the caller's (no leak)
ERROR_SWAP_ALREADY_RESOLVED = "swap_already_resolved"  # 409: left `pending` already
ERROR_SWAP_WRONG_TARGET = "swap_wrong_target"  # 403: only the addressed to_user may act
ERROR_SWAP_SELF = "swap_self"  # 422: both sides are the caller
ERROR_SWAP_ASSIGNMENT_NOT_FOUND = "swap_assignment_not_found"  # 422: no such row
ERROR_SWAP_WRONG_HOLDER = "swap_wrong_holder"  # 422: row not held by the named party
ERROR_SWAP_WEEK_MISMATCH = "swap_week_mismatch"  # 422: rows from different weeks
ERROR_WEEK_NOT_LOCKED = "week_not_locked"  # 409: swaps are post-lock only (§3.4)
ERROR_SWAP_ROLE_INVALID = "swap_role_invalid"  # 422: §4 role compatibility
ERROR_SWAP_WEEKEND_BAGNINI_ONLY = "swap_weekend_bagnini_only"  # 422: H5
ERROR_SWAP_H2_VIOLATION = "swap_h2_violation"  # 422
ERROR_SWAP_H3_VIOLATION = "swap_h3_violation"  # 422
ERROR_SWAP_H4_VIOLATION = "swap_h4_violation"  # 422


class SwapLike(Protocol):
    """The four fields validation needs — satisfied by a `SwapRequest` row (the
    acceptance path) and by `SwapSpec` (the creation path, before a row exists)."""

    @property
    def from_user(self) -> int: ...
    @property
    def to_user(self) -> int: ...
    @property
    def from_assignment(self) -> int: ...
    @property
    def to_assignment(self) -> int: ...


class SwapSpec(NamedTuple):
    """A proposed swap at creation time, shaped like the §6 row it may become."""

    from_user: int
    to_user: int
    from_assignment: int
    to_assignment: int


def validate_swap(db: DbSession, swap_like: SwapLike) -> None:
    """§4: the full server-side validity check — run at creation AND acceptance."""
    _validated_exchange(db, swap_like)


def create_swap(db: DbSession, requester: User, spec: SwapSpec) -> SwapRequest:
    """§4: worker A proposes trading one locked slot with worker B → `pending`."""
    from_a, to_a, week = _validated_exchange(db, spec)
    swap = SwapRequest(
        week_id=week.id,
        from_user=spec.from_user,
        to_user=spec.to_user,
        from_assignment=spec.from_assignment,
        to_assignment=spec.to_assignment,
        status=SwapStatus.PENDING,
    )
    db.add(swap)
    db.flush()  # assign an id for the audit row and the notification payload
    audit.record(
        db,
        requester,
        audit.ACTION_SWAP,
        "swap_request",
        swap.id,
        {"transition": "request", **_exchange_payload(swap, from_a, to_a)},
    )
    # §10: the addressed worker learns a request awaits them. Data only — the
    # frontend dictionaries render it in the viewer's language (§9).
    notify(db, db.get(User, swap.to_user), EVENT_SWAP_REQUESTED, _event_payload(swap, week))
    db.commit()
    return swap


def accept_swap(db: DbSession, swap: SwapRequest, actor: User) -> SwapRequest:
    """§4: the addressed worker accepts. Re-validated in full — the schedule may
    have changed since creation — INSIDE the transaction that applies, so the
    check and the exchange see the same state.

    Flag off: pending → accepted → applied, atomically (the `accepted` state is
    transient — nothing observable sits between consent and application).
    Flag on: pending → accepted → pending_admin, and NO application happens; the
    admin approval endpoint is deliberately deferred (§13) — the state exists,
    the surface does not.
    """
    _require_actionable(db, swap)
    from_a, to_a, week = _validated_exchange(db, swap)  # §4: again at acceptance

    if settings.require_admin_approval:
        swap.status = SwapStatus.PENDING_ADMIN
        swap.resolved_at = utcnow()  # the pause is stamped like a resolution
        audit.record(
            db,
            actor,
            audit.ACTION_SWAP,
            "swap_request",
            swap.id,
            {"transition": "pending_admin", **_exchange_payload(swap, from_a, to_a)},
        )
        _fan_out_accepted(db, swap, week)
        db.commit()
        return swap

    # Atomic application (§4): holders exchanged, provenance restamped, request
    # resolved, ONE audit row, fan-out — one transaction, all or nothing.
    from_a.user_id, to_a.user_id = to_a.user_id, from_a.user_id
    from_a.source = AssignmentSource.SWAP
    to_a.source = AssignmentSource.SWAP
    swap.status = SwapStatus.APPLIED
    swap.resolved_at = utcnow()
    if from_a.day in _WEEKEND_DAYS or to_a.day in _WEEKEND_DAYS:
        # §2.2: `solver_state` records each worker's LAST WORKED SLOT, and H5
        # lets this swap trade Sunday AM for Sunday PM between the two weekend
        # bagnini — the very pair §2.2 names as next Monday's alternation seed.
        # Publishing derived the boundary from these rows; the rows just moved,
        # so re-derive it or next week's S2 term is seeded from a Sunday that
        # did not happen. Same transaction: the schedule and the boundary it
        # implies are never separately true.
        db.flush()  # the exchange must be visible to the re-read below
        write_solver_state(db, week)
    audit.record(
        db,
        actor,
        audit.ACTION_SWAP,
        "swap_request",
        swap.id,
        {"transition": "apply", **_exchange_payload(swap, from_a, to_a)},
    )
    _fan_out_accepted(db, swap, week)
    db.commit()
    return swap


def reject_swap(db: DbSession, swap: SwapRequest, actor: User) -> SwapRequest:
    """§4: the addressed worker refuses → `rejected`, requester notified."""
    _require_actionable(db, swap)
    swap.status = SwapStatus.REJECTED
    swap.resolved_at = utcnow()
    audit.record(
        db,
        actor,
        audit.ACTION_SWAP,
        "swap_request",
        swap.id,
        {"transition": "reject"},
    )
    notify(
        db,
        db.get(User, swap.from_user),
        EVENT_SWAP_REJECTED,
        _event_payload(swap, swap.week),
    )
    db.commit()
    return swap


def is_stale(swap: SwapRequest, now: dt.datetime) -> bool:
    """§4: a `pending` request older than 48 h is due to expire."""
    return swap.status is SwapStatus.PENDING and now - swap.created_at >= SWAP_TTL


def expire_swap(db: DbSession, swap: SwapRequest, now: dt.datetime) -> None:
    """§4: pending → expired. System transition — NULL audit actor (§6), and
    deliberately NO notification: §10's event list is closed and names no expiry
    event. Does not commit; the caller (sweep or lazy check) owns the transaction."""
    swap.status = SwapStatus.EXPIRED
    swap.resolved_at = now
    audit.record(db, None, audit.ACTION_SWAP, "swap_request", swap.id, {"transition": "expire"})


def _require_actionable(db: DbSession, swap: SwapRequest) -> None:
    """409 unless `pending`. Lazily expires an overdue request first (§4): the
    48 h timeout must hold even if the hourly sweep has not fired yet, so an
    accept at hour 49 lands on `expired`, never on a stale `pending`."""
    if is_stale(swap, utcnow()):
        expire_swap(db, swap, utcnow())
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ERROR_SWAP_ALREADY_RESOLVED
        )
    if swap.status is not SwapStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ERROR_SWAP_ALREADY_RESOLVED
        )


def _validated_exchange(db: DbSession, swap: SwapLike) -> tuple[Assignment, Assignment, Week]:
    """The shared §4 validity check. Raises 422/409 on the first failed rule;
    returns the two rows and their week for the caller that goes on to apply."""
    if swap.from_user == swap.to_user:
        raise _invalid(ERROR_SWAP_SELF)
    from_a = db.get(Assignment, swap.from_assignment)
    to_a = db.get(Assignment, swap.to_assignment)
    if from_a is None or to_a is None:
        raise _invalid(ERROR_SWAP_ASSIGNMENT_NOT_FOUND)
    # Distinct rows with the named holders. Re-checked at acceptance on purpose:
    # if another swap or an override moved a row since creation, the holder no
    # longer matches and the stale request is refused instead of misfiring.
    if from_a.user_id != swap.from_user or to_a.user_id != swap.to_user:
        raise _invalid(ERROR_SWAP_WRONG_HOLDER)
    if from_a.week_id != to_a.week_id:
        raise _invalid(ERROR_SWAP_WEEK_MISMATCH)
    week = db.get(Week, from_a.week_id)
    assert week is not None  # FK: an assignment cannot outlive its week
    if week.status is not WeekStatus.LOCKED:
        # §3.4: swaps are the POST-lock instrument; before publish the schedule
        # is not visible, let alone tradeable. State conflict → 409.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_WEEK_NOT_LOCKED)

    # H5: weekend rows are modifiable only via bagnino↔bagnino swap — any swap
    # touching a Sat/Sun row with a spiaggino side is refused outright. Keyed on
    # the DAY, not on source=weekend_template: a weekend row already swapped once
    # carries source=swap but is no less a template day.
    if (from_a.day in _WEEKEND_DAYS or to_a.day in _WEEKEND_DAYS) and (
        from_a.role is not AssignmentRole.BAGNINO or to_a.role is not AssignmentRole.BAGNINO
    ):
        raise _invalid(ERROR_SWAP_WEEKEND_BAGNINI_ONLY)

    # §4 role validity: each party must be able to HOLD the row they would take.
    # By role, never by name — the jolly (role=jolly) matches either (§1).
    requester = db.get(User, swap.from_user)
    target = db.get(User, swap.to_user)
    assert requester is not None and target is not None  # FK via the holder check
    if not _can_hold(requester.role, to_a.role) or not _can_hold(target.role, from_a.role):
        raise _invalid(ERROR_SWAP_ROLE_INVALID)

    _check_h2_h4(db, week, requester, target, from_a, to_a)
    return from_a, to_a, week


def _can_hold(user_role: UserRole, row_role: AssignmentRole) -> bool:
    """§4: bagnino↔bagnino, spiaggino↔spiaggino; the jolly holds either role."""
    if user_role is UserRole.JOLLY:
        return True
    return user_role.value == row_role.value


def _check_h2_h4(
    db: DbSession,
    week: Week,
    requester: User,
    target: User,
    from_a: Assignment,
    to_a: Assignment,
) -> None:
    """§4: H2–H4 must hold for BOTH parties after the hypothetical exchange,
    evaluated against the week's FULL assignment set with the two rows' holders
    swapped — a swap is only role-shuffling if the resulting week is still legal.

    H3/H4 range over Mon–Fri only: the weekend is a template, never solved (H5),
    and its full-day workers legitimately hold two slots a day.
    """
    rows = db.scalars(select(Assignment).where(Assignment.week_id == week.id)).all()
    holders: dict[int, int] = {a.id: a.user_id for a in rows}
    # The hypothetical: the two rows exchange holders, everything else stands.
    holders[from_a.id] = to_a.user_id
    holders[to_a.id] = from_a.user_id

    grants = accepted_sacrifice_grants(db, week)  # v1.6 grant of record (§2.1 H3)
    for party in (requester, target):
        held = [a for a in rows if holders[a.id] == party.id]
        # H2: at most one role per (day, slot) — checked across the whole week,
        # weekend included (holding two roles at once is impossible on any day).
        slot_counts = Counter((a.day, a.slot) for a in held)
        if any(n > 1 for n in slot_counts.values()):
            raise _invalid(ERROR_SWAP_H2_VIOLATION)
        if party.role is UserRole.JOLLY:
            continue  # H6: the jolly may double and holds no H3 free day
        # H4: a core worker works at most one slot per weekday.
        day_counts = Counter(a.day for a in held if a.day in SOLVER_DAYS)
        if any(n > 1 for n in day_counts.values()):
            raise _invalid(ERROR_SWAP_H4_VIOLATION)
        # H3: still exactly one free weekday, inside Mon–Thu ∪ {granted day}.
        free = [d for d in SOLVER_DAYS if day_counts[d] == 0]
        domain = set(FREE_DAYS)
        granted = grants.get(party.id)
        if granted is not None:
            domain.add(granted)
        if len(free) != 1 or free[0] not in domain:
            raise _invalid(ERROR_SWAP_H3_VIOLATION)


def _fan_out_accepted(db: DbSession, swap: SwapRequest, week: Week) -> None:
    """§4/§10: `swap_accepted` → both parties AND the visible admins. Role-based
    half goes through `admin_recipients` (root excluded, §5); the parties are
    addressed individually — root as a *party* is notified like any worker (his
    shifts are real, only the root role is hidden). Deduped by id so an admin who
    is also a party hears once. Called after the status flip, so the payload's
    `status` reflects the outcome (applied vs pending_admin)."""
    payload = _event_payload(swap, week)
    recipients: dict[int, User] = {}
    for uid in (swap.from_user, swap.to_user):
        user = db.get(User, uid)
        assert user is not None  # FK
        recipients[user.id] = user
    for admin in admin_recipients(db):
        recipients.setdefault(admin.id, admin)
    for user in recipients.values():
        notify(db, user, EVENT_SWAP_ACCEPTED, payload)


def _event_payload(swap: SwapRequest, week: Week) -> dict[str, Any]:
    """§10 payload: ids + week monday + the two (day, slot, role) tuples — data
    only, no prose; rendering is the §9 dictionaries' job. Includes the status so
    the pending_admin variant is distinguishable without a second event name."""
    return {
        "swap_id": swap.id,
        "week": week.monday_date.isoformat(),
        "from_user": swap.from_user,
        "to_user": swap.to_user,
        "from_assignment": _assignment_tuple(swap.requester_assignment),
        "to_assignment": _assignment_tuple(swap.target_assignment),
        "status": swap.status.value,
    }


def _assignment_tuple(a: Assignment) -> dict[str, Any]:
    return {"id": a.id, "day": a.day.value, "slot": a.slot.value, "role": a.role.value}


def _exchange_payload(swap: SwapRequest, from_a: Assignment, to_a: Assignment) -> dict[str, Any]:
    """Audit payload: the two assignment ids and both user ids (§4 audit-logged)."""
    return {
        "from_user": swap.from_user,
        "to_user": swap.to_user,
        "from_assignment": from_a.id,
        "to_assignment": to_a.id,
    }


def _invalid(code: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=code)
