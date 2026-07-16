"""In-app notification read routes (spec §7, §10 Channel 1).

The write side is the `notify()` fan-out (§10); this is the read side the frontend
polls every 60 s. Strictly the caller's own rows — a notification is addressed to
one user, and no endpoint here exposes anyone else's.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import select, update

from app.deps import CurrentWorker, DbDep
from app.models import Notification
from app.schemas import MarkReadIn, NotificationOut

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(worker: CurrentWorker, db: DbDep) -> list[Notification]:
    """§7: the caller's own notifications, newest first."""
    stmt = (
        select(Notification)
        .where(Notification.user_id == worker.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
    )
    return list(db.scalars(stmt).all())


@router.post("/notifications/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(body: MarkReadIn, worker: CurrentWorker, db: DbDep) -> None:
    """§7: mark the caller's notifications read. `ids` omitted → all of them; a
    list → only those, and only if they belong to the caller (the `user_id`
    predicate makes another user's id a silent no-op, never a cross-user write)."""
    stmt = update(Notification).where(Notification.user_id == worker.id)
    if body.ids is not None:
        stmt = stmt.where(Notification.id.in_(body.ids))
    db.execute(stmt.values(read=True))
    db.commit()
