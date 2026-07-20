"""Server-side session store and the §7 session cookie.

The spec asks for "server-side sessions (signed cookie, HttpOnly, SameSite=Lax)".
Each of those words is a separate assertion here, plus the two things the
server-side half exists to make possible: logout is a real revocation, and §5's
"deactivation is immediate — it revokes the user's open sessions, not just their
next login".

Nothing reads the wall clock for a decision: every expiry test passes an explicit
`now`, so a slow machine cannot change the outcome.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi import Response
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import Environment, settings
from app.db import utcnow
from app.models import Session
from app.security import sign_token, unsign_token
from app.sessions import (
    clear_session_cookie,
    create_session,
    logout_session,
    purge_expired_sessions,
    resolve_session_user,
    set_session_cookie,
)
from tests.factories import create_worker

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase1

# A fixed instant: all session-lifetime arithmetic is done relative to this.
T0 = dt.datetime(2026, 7, 13, 8, 0, tzinfo=dt.UTC)


def _ttl() -> dt.timedelta:
    return dt.timedelta(hours=settings.session_ttl_hours)


def _cookie_header(response: Response) -> str:
    return response.headers["set-cookie"]


def test_create_session_persists_a_row_for_the_user(session: DbSession) -> None:
    """§6 `sessions`: authority lives in the row, not in the cookie."""
    user = create_worker(session)

    created = create_session(session, user, now=T0)
    session.commit()

    stored = session.get(Session, created.id)
    assert stored is not None
    assert stored.user_id == user.id
    assert stored.created_at == T0
    assert stored.expires_at == T0 + _ttl()


def test_create_session_tokens_are_unguessable_and_unique(session: DbSession) -> None:
    """The token *is* the credential: two sessions must never collide."""
    user = create_worker(session)

    tokens = {create_session(session, user, now=T0).id for _ in range(10)}

    assert len(tokens) == 10
    assert all(len(token) >= 32 for token in tokens)


def test_resolve_session_user_returns_the_live_user(session: DbSession) -> None:
    user = create_worker(session)
    created = create_session(session, user, now=T0)

    assert resolve_session_user(session, created.id, now=T0 + dt.timedelta(hours=1)) == user


def test_resolve_session_user_rejects_an_unknown_token(session: DbSession) -> None:
    create_worker(session)

    assert resolve_session_user(session, "no-such-token", now=T0) is None


def test_resolve_session_user_rejects_an_expired_session(session: DbSession) -> None:
    user = create_worker(session)
    created = create_session(session, user, now=T0)

    just_after_expiry = T0 + _ttl() + dt.timedelta(seconds=1)

    assert resolve_session_user(session, created.id, now=just_after_expiry) is None


def test_resolve_session_user_rejects_a_session_at_its_exact_expiry(session: DbSession) -> None:
    """The boundary is closed: at `expires_at` the session is already over."""
    user = create_worker(session)
    created = create_session(session, user, now=T0)

    just_before_expiry = T0 + _ttl() - dt.timedelta(seconds=1)

    assert resolve_session_user(session, created.id, now=just_before_expiry) == user
    assert resolve_session_user(session, created.id, now=T0 + _ttl()) is None


def test_deactivating_a_user_kills_their_existing_sessions(session: DbSession) -> None:
    """§5: "Deactivation is immediate — it revokes the user's open sessions, not
    just their next login." The session row is untouched; the *resolve* refuses."""
    user = create_worker(session)
    created = create_session(session, user, now=T0)
    assert resolve_session_user(session, created.id, now=T0) == user

    user.active = False
    session.commit()

    assert resolve_session_user(session, created.id, now=T0) is None


def test_logout_session_deletes_the_row(session: DbSession) -> None:
    """Logout is revocation, not just a cleared cookie: a copy of the cookie
    taken before logout must stop working after it."""
    user = create_worker(session)
    created = create_session(session, user, now=T0)
    stolen = created.id

    assert logout_session(session, stolen) is True
    session.commit()

    assert session.get(Session, stolen) is None
    assert resolve_session_user(session, stolen, now=T0) is None


def test_logout_session_is_idempotent(session: DbSession) -> None:
    """Logging out twice is not an error — it just deletes nothing."""
    assert logout_session(session, "no-such-token") is False


def test_logout_session_leaves_other_sessions_alone(session: DbSession) -> None:
    """Logging out of one device must not sign the user out everywhere."""
    user = create_worker(session)
    phone = create_session(session, user, now=T0)
    laptop = create_session(session, user, now=T0)

    logout_session(session, phone.id)
    session.commit()

    assert resolve_session_user(session, laptop.id, now=T0) == user


def test_purge_expired_sessions_removes_only_expired_rows(session: DbSession) -> None:
    """§11's nightly housekeeping. It must not touch a live session."""
    user = create_worker(session)
    stale = create_session(session, user, now=T0 - _ttl() - dt.timedelta(days=1))
    live = create_session(session, user, now=T0)
    session.commit()

    purged = purge_expired_sessions(session, now=T0)
    session.commit()

    assert purged == 1
    assert [row.id for row in session.scalars(select(Session)).all()] == [live.id]
    assert resolve_session_user(session, stale.id, now=T0) is None
    assert resolve_session_user(session, live.id, now=T0) == user


def test_purge_expired_sessions_on_a_clean_store_removes_nothing(session: DbSession) -> None:
    user = create_worker(session)
    create_session(session, user, now=T0)
    session.commit()

    assert purge_expired_sessions(session, now=T0) == 0


def test_session_cookie_is_signed(session: DbSession) -> None:
    """§7: the cookie value is the *signed* token, never the raw row id."""
    user = create_worker(session)
    created = create_session(session, user, now=utcnow())
    response = Response()

    set_session_cookie(response, created)

    cookie = response.headers["set-cookie"]
    value = cookie.split(";")[0].split("=", 1)[1]
    assert value != created.id
    assert value == sign_token(created.id)
    assert unsign_token(value) == created.id


def test_session_cookie_is_httponly_and_samesite_lax(session: DbSession) -> None:
    """§7: `HttpOnly`, `SameSite=Lax`.

    Asserted case-insensitively: Starlette renders `samesite=lax` in lowercase,
    and the attribute names are case-insensitive per RFC 6265.
    """
    user = create_worker(session)
    response = Response()

    set_session_cookie(response, create_session(session, user, now=utcnow()))

    cookie = _cookie_header(response).lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert f"{settings.session_cookie_name}=".lower() in cookie
    assert "path=/" in cookie


def test_session_cookie_is_not_secure_in_dev(
    session: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local dev has no TLS to carry a `Secure` cookie, so login would break."""
    monkeypatch.setattr(settings, "env", Environment.DEV)
    user = create_worker(session)
    response = Response()

    set_session_cookie(response, create_session(session, user, now=utcnow()))

    assert "secure" not in _cookie_header(response).lower()


def test_session_cookie_is_secure_outside_dev(
    session: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§7 + §11: production runs TLS, so the session cookie must not travel in
    the clear."""
    monkeypatch.setattr(settings, "env", Environment.PROD)
    user = create_worker(session)
    response = Response()

    set_session_cookie(response, create_session(session, user, now=utcnow()))

    assert "secure" in _cookie_header(response).lower()


def test_session_cookie_max_age_matches_the_row(session: DbSession) -> None:
    """A cookie outliving its row is a guaranteed 401; a cookie dying early logs
    the user out for no reason. They agree."""
    user = create_worker(session)
    created = create_session(session, user, now=utcnow())
    response = Response()

    set_session_cookie(response, created)

    cookie = _cookie_header(response).lower()
    expected = int((created.expires_at - utcnow()).total_seconds())
    max_age = int(cookie.split("max-age=")[1].split(";")[0])
    assert abs(max_age - expected) <= 5


def test_session_cookie_max_age_is_never_negative(session: DbSession) -> None:
    """An already-expired row must not emit `Max-Age=-3600`, which browsers read
    as a session cookie that lives until the tab closes."""
    user = create_worker(session)
    stale = create_session(session, user, now=utcnow() - _ttl() - dt.timedelta(days=1))
    response = Response()

    set_session_cookie(response, stale)

    assert "max-age=0" in _cookie_header(response).lower()


def test_clear_session_cookie_matches_the_set_attributes(session: DbSession) -> None:
    """Attributes must match `set_session_cookie` or the browser keeps the old
    cookie alongside the deletion."""
    user = create_worker(session)
    set_response = Response()
    set_session_cookie(set_response, create_session(session, user, now=utcnow()))
    clear_response = Response()

    clear_session_cookie(clear_response)

    cleared = _cookie_header(clear_response).lower()
    assert f"{settings.session_cookie_name}=".lower() in cleared
    assert "httponly" in cleared
    assert "samesite=lax" in cleared
    assert "path=/" in cleared
    # An immediate expiry is what makes the browser drop it.
    assert "max-age=0" in cleared or "expires=" in cleared
