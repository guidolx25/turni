"""Server-side session store (spec §6 `sessions`, §7 auth).

The cookie carries a signed opaque token; authority lives in the `sessions` row.
That is what makes logout a real revocation: `logout_session` DELETEs the row, so
a stolen cookie dies with it (a self-contained JWT could not offer that).
"""

from __future__ import annotations

import datetime as dt
import secrets

from fastapi import Response
from sqlalchemy import delete
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import utcnow
from app.models import Session, User
from app.security import sign_token

# 32 bytes -> 43 url-safe chars, inside `sessions.id` String(64) (§6).
_TOKEN_BYTES = 32


def create_session(db: DbSession, user: User, *, now: dt.datetime | None = None) -> Session:
    """Issue a session row for `user` and return it (`.id` is the raw token)."""
    issued_at = now or utcnow()
    session = Session(
        id=secrets.token_urlsafe(_TOKEN_BYTES),
        user_id=user.id,
        created_at=issued_at,
        expires_at=issued_at + dt.timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    db.flush()
    return session


def resolve_session_user(
    db: DbSession, token: str, *, now: dt.datetime | None = None
) -> User | None:
    """Return the live user behind a raw session token, or None.

    None covers all of: unknown token, expired row, deactivated user. §5's
    `active=false` must not authenticate, and checking it here (rather than at
    login only) means deactivating a user kills their open sessions immediately.
    """
    at = now or utcnow()
    session = db.get(Session, token)
    if session is None or session.expires_at <= at:
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.active:
        return None
    return user


def logout_session(db: DbSession, token: str) -> bool:
    """Delete a session row. True if one was there."""
    result = db.execute(delete(Session).where(Session.id == token))
    return bool(result.rowcount)


def revoke_other_sessions(db: DbSession, user: User, keep_token: str | None) -> int:
    """Delete every session of `user` except `keep_token`; returns how many.

    Used by the §7 password change. Changing a password is how a user reacts to
    "someone else has my credentials", so it has to be a real revocation of the
    other devices — the same reasoning §5 applies to deactivation ("revokes the
    user's open sessions, not just their next login"). The caller's own session
    survives, because logging someone out of the browser they just used to fix
    their password is a punishment for doing the right thing.

    `keep_token=None` revokes all of them.
    """
    stmt = delete(Session).where(Session.user_id == user.id)
    if keep_token is not None:
        stmt = stmt.where(Session.id != keep_token)
    return int(db.execute(stmt).rowcount)


def revoke_all_sessions(db: DbSession, user: User) -> int:
    """Delete EVERY session of `user`; returns how many.

    §5's deactivation: "Deactivation is immediate — it revokes the user's open
    sessions, not just their next login." A deactivated user must stop being able
    to act at once, and `resolve_session_user` already refuses an inactive user —
    but relying on that alone would leave live session rows for an account that
    has been removed, so the removal deletes them.

    Also the root password reset (§5 row 7): resetting someone's password is what
    an admin does when that account is compromised or the holder is gone, so the
    device holding the old cookie must be evicted, not merely renamed.
    """
    return revoke_other_sessions(db, user, None)


def purge_expired_sessions(db: DbSession, *, now: dt.datetime | None = None) -> int:
    """Delete every expired session row; returns how many.

    Expiry is already enforced on read, so this is pure housekeeping. It exists
    now so the nightly job (§11) has something to call when APScheduler is wired
    up; nothing schedules it yet.
    """
    at = now or utcnow()
    result = db.execute(delete(Session).where(Session.expires_at <= at))
    return int(result.rowcount)


def set_session_cookie(response: Response, session: Session) -> None:
    """§7: signed, HttpOnly, SameSite=Lax. `Secure` outside dev (§11 runs TLS).

    max_age is derived from the row so the browser and the server agree on when
    the session is over; a cookie outliving its row is just a guaranteed 401.
    """
    max_age = int((session.expires_at - utcnow()).total_seconds())
    response.set_cookie(
        key=settings.session_cookie_name,
        value=sign_token(session.id),
        max_age=max(max_age, 0),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Drop the cookie. Attributes must match `set_session_cookie` or the
    browser keeps the old one alongside the deletion."""
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
