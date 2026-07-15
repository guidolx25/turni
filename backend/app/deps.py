"""Auth + permission dependencies — the spec §5 matrix, in one place.

The tiers are dependencies rather than in-handler checks so that a route's
authority is declared in its signature and cannot be forgotten in a branch. They
chain (`require_admin` depends on `require_worker`), so each tier states only the
one thing it adds:

    worker  = authenticated, active                     (§5 rows 1-2)
    admin   = worker AND (is_admin OR is_root)          (§5 rows 3-6, root inherits)
    root    = worker AND is_root                        (§5 rows 7-8)

New routes pick a tier; they do not re-implement one.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import get_session
from app.models import User
from app.security import unsign_token
from app.sessions import resolve_session_user

# Error details are stable machine codes, not prose: §9 puts every user-visible
# string in the i18n dictionaries, so the frontend maps these to text.
ERROR_NOT_AUTHENTICATED = "not_authenticated"
ERROR_FORBIDDEN = "forbidden"

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_NOT_AUTHENTICATED
)
_FORBIDDEN = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_FORBIDDEN)


def require_worker(
    db: Annotated[DbSession, Depends(get_session)],
    # Aliased off the setting so the cookie the router writes and the cookie this
    # reads cannot drift apart.
    cookie: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> User:
    """§5 baseline: any authenticated, active user.

    Every capability in the matrix starts here — even root's — so a deactivated
    or unauthenticated caller is stopped once, at the bottom of the chain.
    """
    if not cookie:
        raise _UNAUTHENTICATED
    token = unsign_token(cookie)
    if token is None:
        raise _UNAUTHENTICATED
    user = resolve_session_user(db, token)
    if user is None:
        raise _UNAUTHENTICATED
    return user


def require_admin(user: Annotated[User, Depends(require_worker)]) -> User:
    """§5: admin capabilities (solve, override, all submissions, audit).

    Root passes: "Root inherits all admin capabilities" (§5).
    """
    if not (user.is_admin or user.is_root):
        raise _FORBIDDEN
    return user


def require_root(user: Annotated[User, Depends(require_worker)]) -> User:
    """§5: root-only (user management, seeing the root account).

    Deliberately not derived from `require_admin`: root is not "an admin with
    extra", it is its own row in the matrix, and is_admin must never be a path to
    root.
    """
    if not user.is_root:
        raise _FORBIDDEN
    return user


CurrentWorker = Annotated[User, Depends(require_worker)]
CurrentAdmin = Annotated[User, Depends(require_admin)]
CurrentRoot = Annotated[User, Depends(require_root)]
DbDep = Annotated[DbSession, Depends(get_session)]
