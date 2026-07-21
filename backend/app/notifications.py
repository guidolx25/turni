"""The single notification dispatch abstraction (spec §10).

`notify()` is the one entry point every event goes through, so a new channel is
added here without touching a single call site (§10). It ships **Channel 1
(in-app)** — a `notifications` row the frontend polls — and **Channel 2 (email
via Resend, per-user opt-out, templated in the user's language)**. Channel 3 (PWA
push) slots in behind this same function later; the callers never learn which
channels exist, which is the whole point of the abstraction.

Event names are §10's exact strings, kept as constants so a typo cannot silently
create an event nobody listens for. `notifications.event_type` is a free-text
column (§6), so this list can grow without a migration.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import email_templates
from app.email import send_email
from app.models import Notification, User

logger = logging.getLogger(__name__)

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
# §3/§10: the Saturday-17:00 reminder that the Sunday-17:00 submission window is
# 24 h from closing. Per-user (every active worker), not a role fan-out.
EVENT_WINDOW_CLOSING_24H = "window_closing_24h"

# §10's closed event list, TRANSCRIBED — the ten names exactly as the spec writes
# them, as literals rather than as the constants above.
#
# This is the fixed point the other two sets are checked against. `ALL_EVENTS` and
# `email_templates.SUPPORTED_EVENTS` are both derived from code, so comparing them
# to each other only proves they agree: deleting an event from both (or renaming
# it in both) would leave a self-consistent system that no longer implements §10.
# A third, independent transcription of the spec is what makes that a startup
# failure instead of a silent divergence — and the count is asserted too, so an
# event cannot be dropped by editing this tuple alone either.
SPEC_EVENTS: tuple[str, ...] = (
    "schedule_published",
    "swap_requested",
    "swap_accepted",
    "swap_rejected",
    "sacrifice_proposed",
    "sacrifice_resolved",
    "sacrifice_escalated",
    "weekend_hard_escalated",
    "window_closing_24h",
    "admin_override",
)
SPEC_EVENT_COUNT = 10

# The named constants, which is what call sites use.
ALL_EVENTS: frozenset[str] = frozenset(
    {
        EVENT_SCHEDULE_PUBLISHED,
        EVENT_SWAP_REQUESTED,
        EVENT_SWAP_ACCEPTED,
        EVENT_SWAP_REJECTED,
        EVENT_SACRIFICE_PROPOSED,
        EVENT_SACRIFICE_RESOLVED,
        EVENT_SACRIFICE_ESCALATED,
        EVENT_WEEKEND_HARD_ESCALATED,
        EVENT_WINDOW_CLOSING_24H,
        EVENT_ADMIN_OVERRIDE,
    }
)

if len(SPEC_EVENTS) != SPEC_EVENT_COUNT or len(set(SPEC_EVENTS)) != SPEC_EVENT_COUNT:
    raise RuntimeError(
        f"§10 lists exactly {SPEC_EVENT_COUNT} distinct events; SPEC_EVENTS does not"
    )

if frozenset(SPEC_EVENTS) != ALL_EVENTS:
    # Import-time, explicit raise (not `assert`, which `python -O` strips): the
    # constants must spell §10's names, no more and no fewer.
    _drift = ALL_EVENTS.symmetric_difference(SPEC_EVENTS)
    raise RuntimeError(f"§10's event names and the constants disagree on: {sorted(_drift)}")

if ALL_EVENTS != email_templates.SUPPORTED_EVENTS:
    # Import-time, explicit raise (not `assert`, which `python -O` strips): every
    # §10 event must have an email template, and the template registry must not
    # invent events §10 does not list. Combined with the per-event IT/EN guard in
    # `app.email_templates`, this makes "an event with no email, or with only one
    # language" unrepresentable in a running process.
    _difference = ALL_EVENTS.symmetric_difference(email_templates.SUPPORTED_EVENTS)
    raise RuntimeError(f"§10 events and email templates disagree on: {sorted(_difference)}")


def notify(
    db: DbSession, user: User, event_type: str, payload: dict[str, Any] | None = None
) -> None:
    """§10: fan `event_type` out to every enabled channel for `user`.

    Channel 1 (in-app) and Channel 2 (email) today; PWA push is added here later.
    Does not commit — the caller owns the transaction so a notification and the
    state change that triggered it land atomically.

    The email is dispatched inline, so a caller that later rolls back will have
    sent a message about a change that did not happen. Accepted for v1: every
    current call site commits immediately after notifying, and the alternative is
    a persistent outbox, which §10 does not ask for. Never re-order this so a
    channel failure can reach the caller — see `_notify_email`.
    """
    _notify_in_app(db, user, event_type, payload)
    _notify_email(db, user, event_type, payload)


def _notify_in_app(
    db: DbSession, user: User, event_type: str, payload: dict[str, Any] | None
) -> None:
    """Channel 1 (§10): persist a `notifications` row the frontend polls."""
    db.add(Notification(user_id=user.id, event_type=event_type, payload=payload, read=False))


def _referenced_user_ids(payload: Mapping[str, Any] | None) -> set[int]:
    """Every user id this payload mentions, so the email body can name people.

    §10 payloads are DATA — ids, not prose — precisely so the in-app channel can
    localize them in the browser. Email has no browser, so the ids have to become
    names somewhere, and this is the layer that still has a session. Only the
    keys §10's events actually use are read; anything unexpected is ignored
    rather than guessed at.
    """
    if not payload:
        return set()
    ids: set[int] = set()
    for key in ("from_user", "to_user", "user_id", "worker_id"):
        value = payload.get(key)
        if isinstance(value, int):
            ids.add(value)
    conflict = payload.get("conflict")
    if isinstance(conflict, list):
        for item in conflict:
            if isinstance(item, Mapping) and isinstance(item.get("worker_id"), int):
                ids.add(item["worker_id"])
    return ids


def _resolve_names(db: DbSession, payload: dict[str, Any] | None) -> dict[int, str]:
    """`{user_id: display_name}` for the ids in `payload`.

    Root is resolved like anyone else: §5 hides the root ROLE from listings and
    role-based fan-outs, not the man — Matteo works real shifts, and an email
    about a shift he holds must say his name.
    """
    ids = _referenced_user_ids(payload)
    if not ids:
        return {}
    rows = db.scalars(select(User).where(User.id.in_(ids))).all()
    return {row.id: row.display_name for row in rows}


def _notify_email(
    db: DbSession, user: User, event_type: str, payload: dict[str, Any] | None
) -> None:
    """Channel 2 (§10): Resend, per-user opt-out, in the user's language.

    Three gates, all of them silent no-ops rather than errors:

    * `email_notifications` false — the §6/§10 opt-out.
    * no `email` — §6 makes the column nullable; there is nowhere to send.
    * no template — `notifications.event_type` is free text (§6), so an event may
      legitimately be in-app only. Logged, because for a §10 event it would be a
      bug (and the import-time guard above makes that unreachable).

    Cannot raise: `send_email` swallows transport failures (§10 email is a side
    effect of a domain event, never a reason to fail it).
    """
    if not user.email_notifications or not user.email:
        return
    rendered = email_templates.render(
        event_type, user.language, payload, _resolve_names(db, payload)
    )
    if rendered is None:
        logger.warning("no email template for event_type=%s; in-app only", event_type)
        return
    send_email(user.email, rendered.subject, rendered.text, rendered.html)
