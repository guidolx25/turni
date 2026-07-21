"""`PATCH /me/settings` and `POST /me/ics-token` (spec §7, §5, §6 v1.7).

§7 gives the caller exactly three levers over their own account — language, the
email opt-out, and their password — plus (§6 v1.7) regeneration of the ICS feed
credential. The tests here are as much about what the endpoint *cannot* do: it
must be unable to touch `role`, `is_admin`, `is_root` or `active`, and it must
never serialize `is_root` (§5).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.enums import Language
from app.models import AuditLog, User
from app.models import Session as SessionRow
from app.security import verify_password
from tests.factories import PASSWORD, create_root, create_user, create_worker

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase5

NEW_PASSWORD = "una-nuova-password-9876"


def login(client: TestClient, username: str, password: str = PASSWORD) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


# --- preferences ------------------------------------------------------------


def test_patch_updates_language_and_email_preferences(
    session: DbSession, client: TestClient
) -> None:
    user = create_worker(session)
    login(client, user.username)

    response = client.patch(
        "/api/me/settings",
        json={"language": "en", "email_notifications": False},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["language"] == "en"
    assert body["email_notifications"] is False
    session.refresh(user)
    assert user.language is Language.EN


def test_patch_is_partial(session: DbSession, client: TestClient) -> None:
    """An absent field is left alone — not reset to a default."""
    user = create_user(session, "pasha", email="pasha@example.com", language=Language.EN)
    login(client, user.username)

    response = client.patch("/api/me/settings", json={"email_notifications": False})

    assert response.status_code == 200
    assert response.json()["email"] == "pasha@example.com"
    assert response.json()["language"] == "en"


def test_the_address_itself_is_not_settable_here(session: DbSession, client: TestClient) -> None:
    """§7 scopes this endpoint to "language, email_notifications, password change".

    The address decides where §10 Channel 2 mail is delivered, and §5 puts
    account management on root's `/root/users` — so it is not the holder's to
    change here. Structural, not a check: `MeSettingsIn` has no `email` field and
    forbids extras, so the request cannot even express it.
    """
    user = create_user(session, "pasha", email="pasha@example.com")
    login(client, user.username)

    response = client.patch("/api/me/settings", json={"email": "attacker@example.com"})

    assert response.status_code == 422
    session.refresh(user)
    assert user.email == "pasha@example.com", "the address must be untouched"


def test_a_too_short_new_password_is_refused_with_a_renderable_code(
    session: DbSession, client: TestClient
) -> None:
    """§9: the failure must be a CODE the dictionaries can render.

    A pydantic `min_length` would answer 422 with an error *list*, which the
    frontend can only degrade to "something went wrong" — so the length floor is
    enforced in the handler and named like every other error.
    """
    user = create_worker(session)
    login(client, user.username)

    response = client.patch(
        "/api/me/settings",
        json={"current_password": PASSWORD, "new_password": "short"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "new_password_too_short"
    # The old password still works: a refused change changes nothing.
    session.refresh(user)
    assert verify_password(user.password_hash, PASSWORD)


def test_invalid_language_is_rejected(session: DbSession, client: TestClient) -> None:
    user = create_worker(session)
    login(client, user.username)
    assert client.patch("/api/me/settings", json={"language": "de"}).status_code == 422


# --- privilege containment (§5) ---------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [("is_admin", True), ("is_root", True), ("role", "jolly"), ("active", False)],
)
def test_patch_cannot_escalate_privileges(
    session: DbSession, client: TestClient, field: str, value: object
) -> None:
    """§5 puts user management on root's `/root/users`. These fields are absent
    from the request model, so `extra=forbid` rejects the body outright."""
    user = create_worker(session)
    login(client, user.username)

    response = client.patch("/api/me/settings", json={field: value})

    assert response.status_code == 422
    session.refresh(user)
    assert user.is_admin is False
    assert user.is_root is False
    assert user.active is True


def test_response_never_serializes_is_root(session: DbSession, client: TestClient) -> None:
    """§5: `is_root` reaches the wire nowhere — including root's own /me patch."""
    root = create_root(session)
    login(client, root.username)

    response = client.patch("/api/me/settings", json={"language": "en"})

    assert response.status_code == 200
    assert "is_root" not in response.json()


def test_patch_requires_authentication(client: TestClient) -> None:
    assert client.patch("/api/me/settings", json={"language": "en"}).status_code == 401


# --- password change (§7) ---------------------------------------------------


def test_password_change_requires_the_current_password(
    session: DbSession, client: TestClient
) -> None:
    user = create_user(session, "pasha", password=PASSWORD)
    login(client, user.username)

    response = client.patch("/api/me/settings", json={"new_password": NEW_PASSWORD})

    assert response.status_code == 422
    assert response.json()["detail"] == "current_password_required"


def test_password_change_rejects_a_wrong_current_password(
    session: DbSession, client: TestClient
) -> None:
    """A stolen session cookie must not be enough to take the account over."""
    user = create_user(session, "pasha", password=PASSWORD)
    login(client, user.username)
    before = user.password_hash

    response = client.patch(
        "/api/me/settings",
        json={"current_password": "sbagliata-del-tutto", "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "invalid_current_password"
    session.refresh(user)
    assert user.password_hash == before


def test_current_password_without_new_password_is_rejected(
    session: DbSession, client: TestClient
) -> None:
    user = create_user(session, "pasha", password=PASSWORD)
    login(client, user.username)

    response = client.patch("/api/me/settings", json={"current_password": PASSWORD})

    assert response.status_code == 422
    assert response.json()["detail"] == "new_password_required"


def test_password_change_takes_effect(session: DbSession, client: TestClient) -> None:
    user = create_user(session, "pasha", password=PASSWORD)
    login(client, user.username)

    response = client.patch(
        "/api/me/settings", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )
    assert response.status_code == 200

    client.post("/api/auth/logout")
    assert (
        client.post("/api/auth/login", json={"username": "pasha", "password": PASSWORD}).status_code
        == 401
    )
    login(client, "pasha", NEW_PASSWORD)


def test_password_change_revokes_other_sessions_but_not_the_callers(
    session: DbSession, api_client_factory: Callable[..., TestClient]
) -> None:
    """§5's deactivation rule applied to a credential change: the other devices
    are evicted immediately, the browser doing the change stays signed in."""
    user = create_user(session, "pasha", password=PASSWORD)
    other = api_client_factory()
    login(other, user.username)
    changer = api_client_factory()
    login(changer, user.username)
    assert len(session.scalars(select(SessionRow)).all()) == 2

    response = changer.patch(
        "/api/me/settings", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )
    assert response.status_code == 200

    assert changer.get("/api/me").status_code == 200
    assert other.get("/api/me").status_code == 401
    assert len(session.scalars(select(SessionRow)).all()) == 1


def test_password_change_is_audit_logged(session: DbSession, client: TestClient) -> None:
    """Who revoked what, when — never the credential itself."""
    user = create_user(session, "pasha", password=PASSWORD)
    login(client, user.username)

    client.patch(
        "/api/me/settings",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    rows = session.scalars(select(AuditLog).where(AuditLog.action == "credential")).all()
    assert len(rows) == 1
    assert rows[0].actor_id == user.id
    assert rows[0].payload is not None
    assert rows[0].payload["change"] == "password"
    assert NEW_PASSWORD not in str(rows[0].payload)


# --- ICS token regeneration (§6 v1.7) ---------------------------------------


def test_ics_token_regeneration_replaces_the_credential(
    session: DbSession, client: TestClient
) -> None:
    user = create_worker(session)
    login(client, user.username)
    before = client.get("/api/me").json()["ics_token"]

    response = client.post("/api/me/ics-token")

    assert response.status_code == 200
    after = response.json()["ics_token"]
    assert after != before
    session.refresh(user)
    assert user.ics_token == after


def test_old_ics_token_stops_resolving_after_regeneration(
    session: DbSession, client: TestClient
) -> None:
    """Revocation is per-user regeneration (§6 v1.7), so the leaked URL dies."""
    user = create_worker(session)
    login(client, user.username)
    old = user.ics_token

    client.post("/api/me/ics-token")

    # 404 `feed_not_found` is the ICS router's single failure code (it must not
    # distinguish "wrong token" from "no such feed").
    stale = client.get("/api/export/ics", params={"token": old})
    assert stale.status_code == 404
    assert stale.json()["detail"] == "feed_not_found"


def test_ics_regeneration_is_audit_logged(session: DbSession, client: TestClient) -> None:
    user = create_worker(session)
    login(client, user.username)

    client.post("/api/me/ics-token")

    rows = session.scalars(select(AuditLog).where(AuditLog.action == "credential")).all()
    assert len(rows) == 1
    assert rows[0].payload is not None
    assert rows[0].payload["change"] == "ics_token"
    # The new credential itself is never written to the audit log.
    user_row = session.get(User, user.id)
    assert user_row is not None
    assert user_row.ics_token not in str(rows[0].payload)


def test_ics_regeneration_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/me/ics-token").status_code == 401
