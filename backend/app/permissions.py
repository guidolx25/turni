"""The spec §5 capability matrix as pure predicates — the one place it is spelled.

Two consumers read this module and they must never disagree:

  * `app.deps` — the permission dependencies that *enforce* a tier server-side.
  * `GET /me` — the derived booleans that tell the frontend which panels to
    render (§7).

Enforcement and advertisement therefore resolve the same rows through the same
functions. A parallel mapping in the serializer would let the UI offer a button
the API refuses (or hide one it allows); the only way to keep them honest is for
neither to own the matrix.

Authority flows from the flags exactly as §5 states — root *inherits* admin, so
`is_root` alone carries admin capability and `is_admin` is never a path to root.
Callers outside this module should not read `user.is_admin` / `user.is_root` to
make a decision; they should ask a predicate here.
"""

from __future__ import annotations

from app.models import User


def has_admin_capability(user: User) -> bool:
    """§5 rows 3-6 (solve, override, all submissions, audit log).

    Root passes: "Root inherits all admin capabilities" (§5). This is why Matteo
    is seeded `is_root=true, is_admin=false` — one source of authority, not two.
    """
    return user.is_admin or user.is_root


def has_root_capability(user: User) -> bool:
    """§5 rows 7-8 (user management, seeing the root account).

    Not expressed via `has_admin_capability`: root is not "admin plus extra", it
    is its own pair of rows, and `is_admin` must never reach these.
    """
    return user.is_root
