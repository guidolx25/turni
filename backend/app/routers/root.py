"""Root-only routes (spec §7 `-- root --`).

Phase scope is the read side only. POST/PATCH `/root/users` (create/disable
users, reset passwords — §5 row 7) are a later phase and are deliberately absent
rather than stubbed.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import CurrentRoot, DbDep
from app.models import User
from app.schemas import UserAdminOut
from app.visibility import visible_users_stmt

router = APIRouter(prefix="/root", tags=["root"])


@router.get("/users", response_model=list[UserAdminOut])
def list_users(root: CurrentRoot, db: DbDep) -> list[User]:
    """§5: root sees every account, including its own row.

    Routed through `visible_users_stmt` even though the caller is always root and
    the filter is therefore always a no-op here. That is the point: the chokepoint
    is unconditional, so no future listing can be written without passing a viewer
    through it.
    """
    stmt = visible_users_stmt(root).order_by(User.id)
    return list(db.scalars(stmt).all())
