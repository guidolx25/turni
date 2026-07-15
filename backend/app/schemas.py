"""API request/response models (spec §7).

`is_root` is *structurally absent* from every user schema — not excluded by a
conditional, not hidden by an `exclude=` at a call site. §5 makes root's
invisibility a property of the system, and a field that does not exist cannot be
leaked by a branch someone forgets to write. Root-ness reaches the wire only as
the 403 a non-root gets from a root-only route.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.enums import Language, UserRole


class LoginIn(BaseModel):
    """`POST /auth/login` body."""

    # Bounded to keep an absurd body from reaching argon2 (which will happily
    # hash megabytes) or from filling a rate-limit key.
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    """A user as any authenticated caller may see them (§5).

    `is_admin` is here on purpose: §5 makes the admin visible. `is_root` is not,
    and must never be added.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: UserRole
    is_admin: bool
    email: str | None
    email_notifications: bool
    language: Language
    active: bool


class UserAdminOut(UserOut):
    """A user as root may see them (`GET /root/users`, §7).

    Adds only administrative metadata; it inherits UserOut's fields and so
    inherits the absence of `is_root` too.
    """

    created_at: dt.datetime
