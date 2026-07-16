"""The root-invisibility chokepoint `visible_users_stmt` (spec §5).

Every user *enumeration* — endpoints, worker pickers, notification fan-outs —
starts from `app.visibility.visible_users_stmt`. §5 makes root (is_root=true)
invisible in every such listing, visible only to itself. Both branches are proven
here at the statement level (the endpoint can only reach the root branch, since
`/root/users` is root-only), asserting on the exact set of usernames the SELECT
returns so a flipped filter is caught unambiguously rather than by a count that
might coincide.

The UserAdminOut serialization checks (§7: `is_root` never on the wire) live with
the endpoint test here because /root/users is the model's only route.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DbSession

from app.models import User
from app.schemas import UserAdminOut
from app.visibility import visible_users_stmt
from tests.factories import PASSWORD, create_admin, create_root, create_user, create_worker
from tests.probe_app import probe_app


def login(client: TestClient, username: str, password: str = PASSWORD) -> None:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def seed_population(session: DbSession) -> dict[str, User]:
    """A mix with one root row and several non-root, of both system tiers.

    Returned by username so tests assert on the concrete set the SELECT yields.
    """
    return {
        "pasha": create_worker(session, "pasha"),
        "mattia": create_admin(session, "mattia"),
        "amir": create_user(session, "amir"),
        "matteo": create_root(session, "matteo"),
    }


def visible_usernames(session: DbSession, viewer: User | None) -> set[str]:
    return {u.username for u in session.scalars(visible_users_stmt(viewer)).all()}


def test_worker_viewer_never_sees_the_root_row(session: DbSession) -> None:
    """§5: root is hidden from a non-root enumerator — here a plain worker."""
    users = seed_population(session)

    visible = visible_usernames(session, users["pasha"])

    assert "matteo" not in visible
    assert visible == {"pasha", "mattia", "amir"}


def test_admin_viewer_never_sees_the_root_row(session: DbSession) -> None:
    """§5: `is_admin` is not a path to root — the admin's listing excludes root too.

    This is the load-bearing negative: if admin could see root, the "hidden" root
    account would be visible to Mattia in every picker and user list.
    """
    users = seed_population(session)

    visible = visible_usernames(session, users["mattia"])

    assert "matteo" not in visible
    assert visible == {"pasha", "mattia", "amir"}


def test_system_context_viewer_none_never_sees_the_root_row(session: DbSession) -> None:
    """§5 (visibility.py docstring): viewer=None is cron / notification fan-out.

    A system context is not root, so root must stay hidden — a role-based email
    blast must never reach the root account.
    """
    seed_population(session)

    visible = visible_usernames(session, None)

    assert "matteo" not in visible
    assert visible == {"pasha", "mattia", "amir"}


def test_root_viewer_sees_its_own_row_and_everyone(session: DbSession) -> None:
    """§5: root is visible to itself — its listing is the whole population."""
    users = seed_population(session)

    visible = visible_usernames(session, users["matteo"])

    assert "matteo" in visible
    assert visible == set(users)


def test_root_users_endpoint_includes_roots_own_row(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5/§7: through the real route, root's own row (matteo) is in the listing.

    Proves the endpoint, not just the helper — the 403 for worker/admin is covered
    in test_permissions_matrix.py and not repeated here.
    """
    seed_population(session)
    client = api_client_factory(probe_app)
    login(client, "matteo")

    response = client.get("/root/users")

    assert response.status_code == 200, response.text
    usernames = {row["username"] for row in response.json()}
    assert "matteo" in usernames


def test_root_users_never_serializes_is_root(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§7: UserAdminOut is the admin/root-facing view — the highest-risk model.

    A root row is actually in the listing (matteo is seeded), so this is not
    vacuous. Each row's key set is compared to `UserAdminOut.model_fields`, the way
    test_login.py does for UserOut: that catches an `is_root` leak arriving via a
    future field addition, not only the literal key today.
    """
    seed_population(session)
    client = api_client_factory(probe_app)
    login(client, "matteo")

    response = client.get("/root/users")

    assert response.status_code == 200, response.text
    rows = response.json()
    assert rows, "expected a non-empty listing so the assertion is not vacuous"
    for row in rows:
        assert "is_root" not in row
        assert set(row) == set(UserAdminOut.model_fields)
