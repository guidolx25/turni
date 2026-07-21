"""Root user management (spec §5 row 7, §7 `POST/PATCH /root/users`).

§5 states four things this suite pins:

* **No public signup.** Accounts are created by root and by nobody else.
* **`is_root` is not settable.** The build decision is one root account ("5
  account rows, not 6"), and the request models have no such field — a second
  root is unrepresentable, not merely rejected. Nor may the one root deactivate
  itself, which would leave the installation with nobody able to undo it.
* **Users are never hard-deleted.** `active = false` is the only removal.
* **Deactivation is immediate** — "it revokes the user's open sessions, not just
  their next login". That is the load-bearing one: a check on the *next* login
  would leave a removed account acting for the rest of its session's two weeks.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.enums import UserRole
from app.models import AuditLog, Session, User
from tests.factories import PASSWORD, create_full_roster

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase6

NEW_PASSWORD = "una-password-nuova-1234"


def login(client: TestClient, username: str, password: str = PASSWORD) -> None:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text


def _create_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "username": "nuovo",
        "display_name": "Nuovo",
        "role": UserRole.SPIAGGINO.value,
        "email": "nuovo@example.test",
        "is_admin": False,
        "password": NEW_PASSWORD,
    }
    body.update(overrides)
    return body


# --- §5 tier -----------------------------------------------------------------


def test_user_creation_is_root_only(client: TestClient, session: DbSession) -> None:
    """§5 row 7: "Create/disable users, reset passwords" is the ONE row the
    visible admin does not have. Mattia is an admin and is still refused."""
    create_full_roster(session)
    login(client, "mattia")
    assert client.post("/api/root/users", json=_create_body()).status_code == 403


def test_user_creation_has_no_unauthenticated_path(client: TestClient, session: DbSession) -> None:
    """§5: "No public signup." The only creation route is behind the root tier."""
    create_full_roster(session)
    assert client.post("/api/root/users", json=_create_body()).status_code == 401


def test_patch_and_password_reset_are_root_only(client: TestClient, session: DbSession) -> None:
    roster = create_full_roster(session)
    login(client, "mattia")
    target = roster["pasha"].id
    assert client.patch(f"/api/root/users/{target}", json={"active": False}).status_code == 403
    assert (
        client.post(
            f"/api/root/users/{target}/password", json={"new_password": NEW_PASSWORD}
        ).status_code
        == 403
    )


# --- create ------------------------------------------------------------------


def test_root_creates_a_working_account(client: TestClient, session: DbSession) -> None:
    """§5 row 7. The created account is active, non-root, and can log in."""
    create_full_roster(session)
    login(client, "matteo")
    resp = client.post("/api/root/users", json=_create_body())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["username"] == "nuovo"
    assert body["active"] is True
    assert body["is_admin"] is False
    assert "is_root" not in body

    created = session.scalars(select(User).where(User.username == "nuovo")).one()
    assert created.is_root is False
    assert created.password_hash.startswith("$argon2"), "§7: argon2 hashing"
    assert created.ics_token, "§6 v1.7: every account gets a feed credential"

    entry = session.scalars(
        select(AuditLog).where(AuditLog.action == "user").order_by(AuditLog.id.desc())
    ).first()
    assert entry is not None and entry.payload is not None
    assert entry.payload["transition"] == "create"
    assert entry.payload["username"] == "nuovo"

    client.post("/api/auth/logout")
    login(client, "nuovo", NEW_PASSWORD)


def test_is_root_cannot_be_set_through_the_api(client: TestClient, session: DbSession) -> None:
    """§5's build decision is a SINGLE root account. The field does not exist on
    the request model, so `extra="forbid"` rejects the attempt outright — a
    second root is unrepresentable, not merely filtered out."""
    create_full_roster(session)
    login(client, "matteo")
    resp = client.post("/api/root/users", json=_create_body(is_root=True))
    assert resp.status_code == 422
    assert session.scalars(select(User).where(User.username == "nuovo")).one_or_none() is None

    pasha = session.scalars(select(User).where(User.username == "pasha")).one()
    assert client.patch(f"/api/root/users/{pasha.id}", json={"is_root": True}).status_code == 422
    session.expire_all()
    assert session.scalars(select(User).where(User.username == "pasha")).one().is_root is False


def test_a_duplicate_username_is_refused(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    login(client, "matteo")
    resp = client.post("/api/root/users", json=_create_body(username="pasha"))
    assert resp.status_code == 409
    assert resp.json()["detail"] == "username_taken"


def test_a_short_password_is_refused_on_create_and_reset(
    client: TestClient, session: DbSession
) -> None:
    """The same floor `/me/settings` enforces (§7) — it lives in `app.security`
    precisely so the two routes cannot disagree about the system's minimum."""
    roster = create_full_roster(session)
    login(client, "matteo")
    resp = client.post("/api/root/users", json=_create_body(password="corta"))
    assert resp.status_code == 422
    assert resp.json()["detail"] == "new_password_too_short"
    resp = client.post(
        f"/api/root/users/{roster['pasha'].id}/password", json={"new_password": "corta"}
    )
    assert resp.status_code == 422


# --- patch -------------------------------------------------------------------


def test_root_edits_an_account(client: TestClient, session: DbSession) -> None:
    roster = create_full_roster(session)
    login(client, "matteo")
    resp = client.patch(
        f"/api/root/users/{roster['pasha'].id}",
        json={"display_name": "Pasha B.", "is_admin": True, "role": UserRole.JOLLY.value},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["display_name"] == "Pasha B."
    assert body["is_admin"] is True
    assert body["role"] == "jolly"
    assert "is_root" not in body


def test_patch_distinguishes_an_absent_email_from_an_explicit_null(
    client: TestClient, session: DbSession
) -> None:
    """Clearing an address is a real operation (§10 Channel 2 has nowhere to send
    afterwards), so `null` must not be read as "leave alone"."""
    roster = create_full_roster(session)
    roster["pasha"].email = "pasha@example.test"
    session.commit()
    login(client, "matteo")

    untouched = client.patch(f"/api/root/users/{roster['pasha'].id}", json={"display_name": "P"})
    assert untouched.json()["email"] == "pasha@example.test"

    cleared = client.patch(f"/api/root/users/{roster['pasha'].id}", json={"email": None})
    assert cleared.json()["email"] is None


def test_deactivation_revokes_open_sessions_immediately(
    client: TestClient, session: DbSession, api_client_factory: Callable[..., TestClient]
) -> None:
    """§5, verbatim: "Deactivation is immediate — it revokes the user's open
    sessions, not just their next login."

    The victim logs in on their own client, root deactivates them, and their very
    next request must fail — with the session ROW gone, not merely refused by the
    `active` check on read. Both matter: the check is the guarantee, the deletion
    is what stops a removed account's credential from sitting live in the store.
    """
    roster = create_full_roster(session)
    victim_client = api_client_factory()
    login(victim_client, "pasha")
    assert victim_client.get("/api/me").status_code == 200
    assert session.scalars(select(Session).where(Session.user_id == roster["pasha"].id)).all()

    login(client, "matteo")
    resp = client.patch(f"/api/root/users/{roster['pasha'].id}", json={"active": False})
    assert resp.status_code == 200
    assert resp.json()["active"] is False

    session.expire_all()
    assert session.scalars(select(Session).where(Session.user_id == roster["pasha"].id)).all() == []
    assert victim_client.get("/api/me").status_code == 401, "§5: immediate, not next login"

    entry = session.scalars(
        select(AuditLog).where(AuditLog.action == "user").order_by(AuditLog.id.desc())
    ).first()
    assert entry is not None and entry.payload is not None
    assert entry.payload["active"] is False
    assert entry.payload["sessions_revoked"] >= 1


def test_a_deactivated_user_is_never_hard_deleted(client: TestClient, session: DbSession) -> None:
    """§5: "Users are never hard-deleted ... a deletion would either destroy
    history or leave the audit log lying about who acted." The row survives, and
    root can still see it."""
    roster = create_full_roster(session)
    login(client, "matteo")
    client.patch(f"/api/root/users/{roster['pasha'].id}", json={"active": False})

    session.expire_all()
    still_there = session.get(User, roster["pasha"].id)
    assert still_there is not None and still_there.active is False
    listed = client.get("/api/root/users").json()
    assert roster["pasha"].id in {u["id"] for u in listed}


def test_root_cannot_deactivate_itself(client: TestClient, session: DbSession) -> None:
    """§5: only root can create users, reset passwords or reactivate an account.
    An installation with zero active roots cannot be repaired from inside the
    app, so the last one is refused."""
    roster = create_full_roster(session)
    login(client, "matteo")
    resp = client.patch(f"/api/root/users/{roster['matteo'].id}", json={"active": False})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "last_root_required"

    session.expire_all()
    assert session.get(User, roster["matteo"].id).active is True
    assert client.get("/api/me").status_code == 200, "and he is still logged in"


# --- password reset ----------------------------------------------------------


def test_root_resets_a_password_and_evicts_the_holder(
    client: TestClient, session: DbSession, api_client_factory: Callable[..., TestClient]
) -> None:
    """§5 row 7. A reset happens because the credential is compromised or the
    holder is gone, so every session of that user goes with it — the same
    reasoning §5 gives for deactivation."""
    roster = create_full_roster(session)
    victim_client = api_client_factory()
    login(victim_client, "pasha")

    login(client, "matteo")
    resp = client.post(
        f"/api/root/users/{roster['pasha'].id}/password", json={"new_password": NEW_PASSWORD}
    )
    assert resp.status_code == 200, resp.text

    session.expire_all()
    assert session.scalars(select(Session).where(Session.user_id == roster["pasha"].id)).all() == []
    assert victim_client.get("/api/me").status_code == 401
    stale = victim_client.post("/api/auth/login", json={"username": "pasha", "password": PASSWORD})
    assert stale.status_code == 401, "the old password must be dead"
    login(victim_client, "pasha", NEW_PASSWORD)

    entry = session.scalars(
        select(AuditLog).where(AuditLog.action == "credential").order_by(AuditLog.id.desc())
    ).first()
    assert entry is not None and entry.payload is not None
    assert entry.payload["change"] == "password_reset"
    assert entry.actor_id == roster["matteo"].id
    assert entry.entity_id == roster["pasha"].id


def test_root_resetting_its_own_password_keeps_the_current_session(
    client: TestClient, session: DbSession
) -> None:
    """Logging someone out of the browser they just used to fix their own
    credentials punishes them for doing it; §7's `/me/settings` change makes the
    same allowance, and root has no one else to let it back in."""
    roster = create_full_roster(session)
    login(client, "matteo")
    resp = client.post(
        f"/api/root/users/{roster['matteo'].id}/password", json={"new_password": NEW_PASSWORD}
    )
    assert resp.status_code == 200
    assert client.get("/api/me").status_code == 200


def test_password_reset_404s_an_unknown_user(client: TestClient, session: DbSession) -> None:
    create_full_roster(session)
    login(client, "matteo")
    resp = client.post("/api/root/users/9999/password", json={"new_password": NEW_PASSWORD})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "user_not_found"
