"""Audit-log helper (spec §6 `audit_log`, §5 "view audit log").

Every lock, publish, swap, override and sacrifice transition is recorded here.
`actor_id` is nullable: a scheduled job (§11 cron solve, §4 swap expiry) acts with
no human actor, and those transitions are logged too. Passing `actor=None` records
exactly that — a system action — without inventing a system user row (§6).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session as DbSession

from app.models import AuditLog, User

# Action verbs. Named so the audit view (§5) filters on a stable vocabulary.
ACTION_PUBLISH = "publish"
ACTION_SOLVE = "solve"
ACTION_OVERRIDE = "override"
ACTION_SACRIFICE = "sacrifice"
# §4/§6: every swap_request state transition (request, apply, reject, expire,
# pending_admin) — the 48 h expiry logs with a NULL actor (system).
ACTION_SWAP = "swap"
# A user changing their own credentials (§7 PATCH /me/settings password change,
# POST /me/ics-token). Not one of §6's enumerated state transitions, but both are
# revocations — of the other sessions, of a leaked calendar feed — and "who
# revoked what, when" is exactly what the audit log is for. Never records the
# credential itself, only that it changed.
ACTION_CREDENTIAL = "credential"
# §5 row 7: root creating or editing an account (including deactivation, the only
# removal §5 permits). A password RESET is `ACTION_CREDENTIAL` instead, so "who
# reset whose password" filters apart from "who changed whose role".
ACTION_USER = "user"
# §11's nightly SQLite backup. A system action with a NULL actor (§6), logged so
# an operator can establish from the audit trail that backups actually ran — and
# notice from the payload when one did not.
ACTION_BACKUP = "backup"
# A conflict handed to a human because no automated path can resolve it (today:
# a HARD H7 request on an H5 template day, escalated at submission).
ACTION_ESCALATE = "escalate"


def record(
    db: DbSession,
    actor: User | None,
    action: str,
    entity: str,
    entity_id: int | None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Append one audit row. Does not commit — it shares the caller's transaction
    so the record and the change it describes commit together or not at all."""
    db.add(
        AuditLog(
            actor_id=actor.id if actor is not None else None,
            action=action,
            entity=entity,
            entity_id=entity_id,
            payload=payload,
        )
    )
