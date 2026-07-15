"""Auth routes: `POST /auth/login`, `POST /auth/logout`, `GET /me` (spec §7).

No signup route exists and none may be added: §5 is explicit that there is no
public signup — accounts are seeded or created by root.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentWorker, DbDep
from app.models import User
from app.ratelimit import SlidingWindowRateLimiter
from app.schemas import LoginIn, UserOut
from app.security import (
    dummy_password_hash,
    hash_password,
    password_needs_rehash,
    unsign_token,
    verify_password,
)
from app.sessions import clear_session_cookie, create_session, logout_session, set_session_cookie

router = APIRouter(tags=["auth"])

# §7: keyed per-username AND per-IP, independently. Per-username alone lets a
# botnet spray one attempt each at every account from one host; per-IP alone lets
# a distributed attacker hammer a single account. Neither subsumes the other.
# Counters are per-process and reset on restart BY DESIGN — see app.ratelimit.
_username_limiter = SlidingWindowRateLimiter(
    settings.login_max_attempts, settings.login_window_seconds
)
_ip_limiter = SlidingWindowRateLimiter(settings.login_max_attempts, settings.login_window_seconds)

ERROR_INVALID_CREDENTIALS = "invalid_credentials"
ERROR_RATE_LIMITED = "rate_limited"


def _client_ip(request: Request) -> str:
    """The peer address as Starlette sees it.

    Deliberately does NOT parse X-Forwarded-For: an unvalidated XFF is
    attacker-supplied and would make the per-IP limit trivially bypassable. When
    §11's deployment puts a proxy in front, uvicorn's `--proxy-headers` (with a
    trusted-hosts list) is what rewrites `request.client` correctly.
    """
    return request.client.host if request.client else "unknown"


def _authenticate(db: DbDep, credentials: LoginIn) -> User | None:
    """Password check with a uniform cost whether or not the username exists.

    An unknown username is verified against a throwaway hash so the response time
    does not enumerate accounts (§7). Same for an inactive user: we spend the
    argon2 verify and then refuse, rather than short-circuiting on `active`.
    """
    user = db.scalars(select(User).where(User.username == credentials.username)).one_or_none()
    stored_hash = user.password_hash if user is not None else dummy_password_hash()
    password_ok = verify_password(stored_hash, credentials.password)

    # §5: `active=false` must not authenticate.
    if user is None or not password_ok or not user.active:
        return None

    # Transparent upgrade: the plaintext is only available right here, so this is
    # the one moment a hash made with older argon2 parameters can be replaced.
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(credentials.password)
        db.add(user)

    return user


@router.post("/auth/login", response_model=UserOut)
def login(request: Request, response: Response, credentials: LoginIn, db: DbDep) -> User:
    """§7: session-cookie login."""
    ip = _client_ip(request)
    username_key = credentials.username.casefold()

    if _username_limiter.is_limited(username_key) or _ip_limiter.is_limited(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=ERROR_RATE_LIMITED
        )

    user = _authenticate(db, credentials)
    if user is None:
        _username_limiter.register_failure(username_key)
        _ip_limiter.register_failure(ip)
        # One code for every failure mode: "no such user", "wrong password" and
        # "deactivated" must be indistinguishable to the caller.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERROR_INVALID_CREDENTIALS
        )

    _username_limiter.reset(username_key)
    _ip_limiter.reset(ip)

    session = create_session(db, user)
    db.commit()
    set_session_cookie(response, session)
    return user


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: DbDep,
    cookie: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> Response:
    """Revoke the session row and clear the cookie.

    Not behind `require_worker`: logging out with an already-dead session is not
    an error, and answering 401 here would strand a client holding a stale
    cookie. Idempotent by design.
    """
    if cookie:
        token = unsign_token(cookie)
        if token is not None:
            logout_session(db, token)
            db.commit()
    clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserOut)
def me(user: CurrentWorker) -> User:
    """§7: the caller's own account. Root sees itself here (§5) — this is a
    self-lookup, not an enumeration, so `visible_users_stmt` does not apply."""
    return user
