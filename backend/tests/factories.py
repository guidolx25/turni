"""ORM-level account builders for the auth/permission suites (spec §5, §7).

Distinct from `tests.helpers`, which writes rows as literal SQL to interrogate
the DDL. Here the subject is application behaviour — a `User` the permission
predicates and the session store can actually be handed — so the ORM is the right
layer and `app.security.hash_password` produces a hash `POST /auth/login` will
really verify.

argon2 is deliberately expensive (§7). Every account that does not need its own
password shares one, hashed once per session.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy.orm import Session as DbSession

from app.enums import Language, UserRole
from app.models import User
from app.security import hash_password

PASSWORD = "la-password-corretta-1234"


@lru_cache(maxsize=1)
def shared_password_hash() -> str:
    """The hash of `PASSWORD`, computed once (argon2 costs ~100 ms a go)."""
    return hash_password(PASSWORD)


def create_user(
    db: DbSession,
    username: str,
    *,
    role: UserRole = UserRole.BAGNINO,
    display_name: str | None = None,
    is_admin: bool = False,
    is_root: bool = False,
    active: bool = True,
    password: str | None = None,
    email: str | None = None,
    language: Language = Language.IT,
) -> User:
    """Persist one §6 `users` row. Defaults to a plain, active worker."""
    user = User(
        username=username,
        password_hash=shared_password_hash() if password is None else hash_password(password),
        display_name=display_name or username.capitalize(),
        role=role,
        is_admin=is_admin,
        is_root=is_root,
        active=active,
        email=email,
        language=language,
    )
    db.add(user)
    db.commit()
    return user


def create_worker(db: DbSession, username: str = "pasha") -> User:
    """§1: Pasha — a plain worker (spiaggino), no system role."""
    return create_user(db, username, role=UserRole.SPIAGGINO)


def create_admin(db: DbSession, username: str = "mattia") -> User:
    """§1: Mattia — jolly (both roles, H6) and the *visible* admin."""
    return create_user(db, username, role=UserRole.JOLLY, is_admin=True)


def create_root(db: DbSession, username: str = "matteo") -> User:
    """§1/§5: Matteo — one account holding worker + hidden root.

    `is_admin` stays false: §5 says root *inherits* admin capability, so the
    authority comes from `is_root`. An account with both flags would prove
    nothing about inheritance.
    """
    return create_user(db, username, role=UserRole.BAGNINO, is_root=True)
