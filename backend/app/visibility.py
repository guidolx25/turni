"""The single chokepoint for enumerating users (spec §5 root invisibility).

Every endpoint, picker and notification fan-out that produces a *set* of users
starts from `visible_users_stmt`. Nothing else may `select(User)` for a listing:
one filter written once cannot regress in the copy nobody remembered to update.

Looking a user up by their own id (e.g. `GET /me`, a session's owner) is not an
enumeration and does not belong here — root is visible to itself (§5).
"""

from __future__ import annotations

from sqlalchemy import Select, select

from app.models import User


def visible_users_stmt(viewer: User | None) -> Select[tuple[User]]:
    """Spec §5: root (is_root=true) is hidden from user lists, worker pickers,
    and role-based notification fan-outs; visible only to itself.
    viewer=None means a system context (cron, notification fan-out) -> root hidden.
    Returns a composable SELECT; callers add their own filters/ordering.
    """
    stmt = select(User)
    if viewer is not None and viewer.is_root:
        return stmt
    return stmt.where(User.is_root.is_(False))
