"""Auth + own-account routes: `POST /auth/login`, `POST /auth/logout`, `GET /me`,
`PATCH /me/settings`, `POST /me/ics-token` (spec §7).

No signup route exists and none may be added: §5 is explicit that there is no
public signup — accounts are seeded or created by root. The `/me` routes are the
counterpart of that rule: a user may change their own preferences and their own
credentials here, and nothing else — every field that carries authority (§5) is
absent from the request model, not merely rejected by a check.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from sqlalchemy import select

from app import audit
from app.config import settings
from app.deps import CurrentWorker, DbDep
from app.models import User
from app.ratelimit import SlidingWindowRateLimiter
from app.schemas import LoginIn, MeOut, MeSettingsIn, UserOut
from app.security import (
    dummy_password_hash,
    hash_password,
    new_ics_token,
    password_needs_rehash,
    unsign_token,
    verify_password,
)
from app.sessions import (
    clear_session_cookie,
    create_session,
    logout_session,
    revoke_other_sessions,
    set_session_cookie,
)

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
# §7 PATCH /me/settings. Machine codes, not prose — §9 keeps every user-visible
# string in the i18n dictionaries.
ERROR_INVALID_CURRENT_PASSWORD = "invalid_current_password"
ERROR_CURRENT_PASSWORD_REQUIRED = "current_password_required"
ERROR_NEW_PASSWORD_REQUIRED = "new_password_required"
ERROR_NEW_PASSWORD_TOO_SHORT = "new_password_too_short"

# A floor the spec does not set: enough that this endpoint cannot be used to
# weaken an account to a one-character password.
MIN_PASSWORD_LENGTH = 8


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


@router.get("/me", response_model=MeOut)
def me(user: CurrentWorker) -> MeOut:
    """§7: the caller's own account plus their derived §5 capabilities.

    Root sees itself here (§5) — this is a self-lookup, not an enumeration, so
    `visible_users_stmt` does not apply. The capabilities are why this route does
    not answer UserOut: authority is not readable off `is_admin` alone (root
    holds it via `is_root`, which never serializes), so /me states the rows
    outright rather than leaving the frontend to infer them from a flag.
    """
    return MeOut.for_user(user)


def _current_token(cookie: str | None) -> str | None:
    """The caller's own session token, or None if the cookie is absent/forged.

    A None here only widens the revocation (every session goes), so a forged
    cookie cannot use this to *keep* a session alive.
    """
    return unsign_token(cookie) if cookie else None


def _apply_password_change(db: DbDep, user: User, body: MeSettingsIn, cookie: str | None) -> None:
    """§7 password change: verify the current password, rehash, revoke elsewhere.

    Requiring the current password is what stops a stolen session cookie from
    becoming permanent account takeover. On success the user's OTHER sessions are
    deleted (mirroring §5's "deactivation revokes open sessions"), so a change
    made because a device was lost actually evicts that device; the caller's own
    session survives, so they are not logged out of the browser they just used.
    """
    if body.new_password is None:
        # A current_password with no new_password is a half-formed request, not a
        # no-op: answering 200 would tell the caller a change happened.
        if body.current_password is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=ERROR_NEW_PASSWORD_REQUIRED,
            )
        return

    if body.current_password is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_CURRENT_PASSWORD_REQUIRED,
        )
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_INVALID_CURRENT_PASSWORD
        )
    # Checked here rather than as a Field constraint so the failure is a code the
    # §9 dictionaries can render, not pydantic's error list (which the frontend
    # can only degrade to "something went wrong").
    if len(body.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_NEW_PASSWORD_TOO_SHORT,
        )

    user.password_hash = hash_password(body.new_password)
    revoked = revoke_other_sessions(db, user, _current_token(cookie))
    audit.record(
        db,
        user,
        audit.ACTION_CREDENTIAL,
        "user",
        user.id,
        {"change": "password", "sessions_revoked": revoked},
    )


@router.patch("/me/settings", response_model=MeOut)
def update_settings(
    body: MeSettingsIn,
    user: CurrentWorker,
    db: DbDep,
    cookie: Annotated[str | None, Cookie(alias=settings.session_cookie_name)] = None,
) -> MeOut:
    """§7: the caller's own preferences (language, email opt-out, address) and
    their own password.

    A partial patch — an absent field is untouched. Nothing here can reach
    `role`, `is_admin`, `is_root`, `active` or `ics_token`: `MeSettingsIn` has no
    such fields and forbids extras, so those are not rejected by a check that
    could be forgotten, they are unrepresentable in the request.

    `language` is the setting §10 Channel 2 reads to pick the email template, so
    changing it here changes the language of the next email.
    """
    if body.language is not None:
        user.language = body.language
    if body.email_notifications is not None:
        user.email_notifications = body.email_notifications
    _apply_password_change(db, user, body, cookie)

    db.add(user)
    db.commit()
    db.refresh(user)
    return MeOut.for_user(user)


@router.post("/me/ics-token", response_model=MeOut)
def regenerate_ics_token(user: CurrentWorker, db: DbDep) -> MeOut:
    """§6 (v1.7): mint a fresh `/export/ics` credential for the caller.

    The calendar-feed URL is the leakiest credential in the system — pasted into
    calendar apps, synced to family devices — so §6 makes revocation a *per-user
    regeneration*, never a SECRET_KEY rotation that would log everyone out. The
    old token stops resolving the moment this commits; the user re-subscribes
    with the new URL, which /me returns (the only schema allowed to carry it).
    """
    user.ics_token = new_ics_token()
    audit.record(db, user, audit.ACTION_CREDENTIAL, "user", user.id, {"change": "ics_token"})
    db.add(user)
    db.commit()
    db.refresh(user)
    return MeOut.for_user(user)
