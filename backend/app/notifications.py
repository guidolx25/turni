"""The single notification dispatch abstraction (spec §10).

`notify()` is the one entry point every event goes through, so a new channel is
added here without touching a single call site (§10). v1 ships **Channel 1
(in-app)** only: a `notifications` row the frontend polls. Channel 2 (email via
Resend, per-user opt-out, templated in the user's language) and Channel 3 (PWA
push) slot in behind this function in Phase 5 / later — the callers never learn
which channels exist.

Event names are §10's exact strings, kept as constants so a typo cannot silently
create an event nobody listens for. `notifications.event_type` is a free-text
column (§6), so this list can grow without a migration.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as DbSession

from app.models import Notification, User

# §10 events. Only the ones a wired path emits today are defined; the rest arrive
# with their features (swaps → Phase 4, the reminder cron → later).
EVENT_SCHEDULE_PUBLISHED = "schedule_published"
EVENT_SACRIFICE_PROPOSED = "sacrifice_proposed"
EVENT_SACRIFICE_RESOLVED = "sacrifice_resolved"
# §2.3 escalation to the admin is a distinct hand-off from a resolution: it carries
# the conflict explanation for an UNRESOLVED week, so it must not be conflated with
# `sacrifice_resolved`. Ratified in §10 (spec v1.3), which now lists
# `sacrifice_escalated` alongside the other `sacrifice_*` events (free-text column,
# no migration needed) — no behavior change.
EVENT_SACRIFICE_ESCALATED = "sacrifice_escalated"
# H5 makes Sat/Sun a fixed template the solver never touches, so a HARD H7 request
# on a weekend day has no variable to bind and cannot be honored by solving. §2.3
# forbids resolving that silently, so submission escalates it to the admin, who
# reconciles it against the template by hand.
# §10 enumerates this event and defines its audience (visible admins only) and its
# firing rule: on creation of a hard weekend request, including a soft→hard change,
# but never on re-submission of an already-hard row and never on deletion.
EVENT_WEEKEND_HARD_ESCALATED = "weekend_hard_escalated"
EVENT_ADMIN_OVERRIDE = "admin_override"
# §4 swap lifecycle. Requested → the addressed worker; accepted → both parties
# AND the visible admins (§4 "both parties + admin notified", root excluded via
# app.visibility); rejected → the requester. §10's event list is closed: the
# 48 h expiry deliberately has NO event.
EVENT_SWAP_REQUESTED = "swap_requested"
EVENT_SWAP_ACCEPTED = "swap_accepted"
EVENT_SWAP_REJECTED = "swap_rejected"


def notify(
    db: DbSession, user: User, event_type: str, payload: dict[str, Any] | None = None
) -> None:
    """§10: fan `event_type` out to every enabled channel for `user`.

    Today that is only the in-app channel; email and PWA push are added inside
    this function later, which is the whole point of routing every event through
    one abstraction. Does not commit — the caller owns the transaction so a
    notification and the state change that triggered it land atomically.
    """
    _notify_in_app(db, user, event_type, payload)


def _notify_in_app(
    db: DbSession, user: User, event_type: str, payload: dict[str, Any] | None
) -> None:
    """Channel 1 (§10): persist a `notifications` row the frontend polls."""
    db.add(Notification(user_id=user.id, event_type=event_type, payload=payload, read=False))
