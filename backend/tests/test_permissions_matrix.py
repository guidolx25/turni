"""The spec §5 capability matrix: predicates and their enforcement.

Two layers, because §5 is claimed in two places:

* `app.permissions` — the matrix as pure predicates.
* `app.deps` — the dependencies that turn a predicate into a 401/403.

The rows under test are the ones §5 restricts. The two unconditional rows
("submit/edit own constraints", "view schedule, request/accept swaps") are the
worker tier itself, covered by `/probe/worker`.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DbSession

from app.deps import ERROR_FORBIDDEN, ERROR_NOT_AUTHENTICATED
from app.permissions import has_admin_capability, has_root_capability
from app.security import sign_token
from tests.factories import PASSWORD, create_admin, create_root, create_user, create_worker
from tests.probe_app import probe_app

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase1


def login(client: TestClient, username: str, password: str = PASSWORD) -> None:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


# --- the matrix as predicates (app.permissions) ---


def test_has_admin_capability_is_false_for_a_plain_worker(session: DbSession) -> None:
    """§5 rows 3-6: workers have no admin capability."""
    assert has_admin_capability(create_worker(session)) is False


def test_has_admin_capability_is_true_for_the_admin(session: DbSession) -> None:
    """§5: Mattia is the visible admin."""
    assert has_admin_capability(create_admin(session)) is True


def test_has_admin_capability_is_true_for_root(session: DbSession) -> None:
    """§5: "Root inherits all admin capabilities" — with is_admin false, so the
    inheritance is real and not a second flag set at seed time."""
    root = create_root(session)

    assert root.is_admin is False
    assert has_admin_capability(root) is True


def test_has_root_capability_is_false_for_a_plain_worker(session: DbSession) -> None:
    assert has_root_capability(create_worker(session)) is False


def test_has_root_capability_is_false_for_the_admin(session: DbSession) -> None:
    """§5 rows 7-8 are root's alone: `is_admin` is never a path to root."""
    assert has_root_capability(create_admin(session)) is False


def test_has_root_capability_is_true_for_root(session: DbSession) -> None:
    assert has_root_capability(create_root(session)) is True


def test_root_capability_does_not_leak_through_the_admin_flag(session: DbSession) -> None:
    """An account carrying both flags is still just an admin plus root — neither
    predicate is defined in terms of the other."""
    both = create_user(session, "both", is_admin=True, is_root=True)

    assert has_admin_capability(both) is True
    assert has_root_capability(both) is True


# --- enforcement (app.deps) ---


def test_unauthenticated_is_401_not_403(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """401 means "log in", 403 means "you may not". A caller with no session must
    get the former or the frontend cannot tell them what to do."""
    create_worker(session)
    client = api_client_factory(probe_app)

    for path in ("/probe/worker", "/probe/admin", "/probe/root", "/root/users", "/me"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["detail"] == ERROR_NOT_AUTHENTICATED


def test_worker_reaches_the_worker_tier(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5 rows 1-2: every authenticated, active user holds these."""
    create_worker(session, "pasha")
    client = api_client_factory(probe_app)
    login(client, "pasha")

    assert client.get("/probe/worker").status_code == 200


def test_worker_is_forbidden_from_the_admin_tier(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5 rows 3-6 are dashes for a worker."""
    create_worker(session, "pasha")
    client = api_client_factory(probe_app)
    login(client, "pasha")

    response = client.get("/probe/admin")
    assert response.status_code == 403
    assert response.json()["detail"] == ERROR_FORBIDDEN


def test_worker_is_forbidden_from_the_root_tier(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5 rows 7-8 are dashes for a worker."""
    create_worker(session, "pasha")
    client = api_client_factory(probe_app)
    login(client, "pasha")

    assert client.get("/probe/root").status_code == 403
    assert client.get("/root/users").status_code == 403


def test_admin_reaches_the_admin_tier(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5 rows 3-6 for Mattia: solve, override, all submissions, audit log."""
    create_admin(session)
    client = api_client_factory(probe_app)
    login(client, "mattia")

    assert client.get("/probe/admin").status_code == 200


def test_admin_is_forbidden_from_the_root_tier(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5: create/disable users and seeing the root account are root's alone.

    This is the load-bearing negative of the matrix: `is_admin` must never be a
    path to root, or the "hidden" root account is visible to Mattia.
    """
    create_admin(session)
    client = api_client_factory(probe_app)
    login(client, "mattia")

    for path in ("/probe/root", "/root/users"):
        response = client.get(path)
        assert response.status_code == 403, path
        assert response.json()["detail"] == ERROR_FORBIDDEN


def test_root_inherits_the_admin_tier(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5: "Root inherits all admin capabilities" — including with is_admin false."""
    root = create_root(session)
    client = api_client_factory(probe_app)
    login(client, "matteo")

    assert root.is_admin is False
    assert client.get("/probe/worker").status_code == 200
    assert client.get("/probe/admin").status_code == 200
    assert client.get("/probe/root").status_code == 200
    assert client.get("/root/users").status_code == 200


def test_deactivated_user_is_refused_at_the_bottom_of_the_chain(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5: deactivation revokes open sessions immediately — 401 (the session is
    no longer valid), not 403."""
    root = create_root(session)
    client = api_client_factory(probe_app)
    login(client, "matteo")
    assert client.get("/probe/root").status_code == 200

    root.active = False
    session.commit()

    for path in ("/probe/worker", "/probe/admin", "/probe/root", "/me"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["detail"] == ERROR_NOT_AUTHENTICATED


def test_forged_cookies_never_reach_a_tier(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§7: the cookie is signed, so garbage is refused by HMAC before the session
    table is ever consulted — and a *validly signed* unknown token is refused by
    the store, which is what makes the signature a filter rather than the auth."""
    from app.config import settings

    create_root(session)
    client = api_client_factory(probe_app)
    login(client, "matteo")
    good = client.cookies[settings.session_cookie_name]

    forgeries = {
        "garbage": "not-a-cookie-at-all",
        "unsigned_token": good.rpartition(".")[0],
        "tampered_payload": "x" + good,
        "tampered_signature": good[:-1] + ("A" if good[-1] != "A" else "B"),
        "truncated": good[: len(good) // 2],
        "empty": "",
        # Correctly signed, but names no session row.
        "signed_unknown_token": sign_token("token-that-was-never-issued"),
    }

    for name, value in forgeries.items():
        client.cookies.set(settings.session_cookie_name, value)
        response = client.get("/probe/root")
        assert response.status_code == 401, name
        assert response.json()["detail"] == ERROR_NOT_AUTHENTICATED
