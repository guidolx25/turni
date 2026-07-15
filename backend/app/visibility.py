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
from app.permissions import has_root_capability


def visible_users_stmt(viewer: User | None) -> Select[tuple[User]]:
    """Spec §5: root (is_root=true) is hidden from user lists, worker pickers,
    and role-based notification fan-outs; visible only to itself.
    viewer=None means a system context (cron, notification fan-out) -> root hidden.
    Returns a composable SELECT; callers add their own filters/ordering.
    """
    stmt = select(User)
    # Who may see root is §5's last matrix row — the same row /me reports as
    # `capabilities.see_root_account`. Both resolve it through the predicate, so
    # the filter and the advertisement cannot drift into disagreeing about who
    # root is visible to. The `is_root` column read below is the *subject* of the
    # filter, not a tier decision.
    if viewer is not None and has_root_capability(viewer):
        return stmt
    return stmt.where(User.is_root.is_(False))
