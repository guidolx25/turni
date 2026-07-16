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
