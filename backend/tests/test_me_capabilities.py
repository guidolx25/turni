"""`GET /me` capability derivation (spec §5 matrix, §7 `/me`).

The point under test is that `Capabilities.for_user` maps §5 matrix rows onto the
*predicates* in `app.permissions`, not onto a second reading of `is_admin` /
`is_root`. The load-bearing case is root: §5 says root inherits admin capability,
yet root is seeded `is_admin=false`, so any re-derivation that hardcoded e.g.
`trigger_solve=user.is_admin` would silently drop root's admin rows here while the
dependencies (`app.deps`) still enforced them. Each test computes its expectation
from the same predicates the enforcement uses, so agreement — not a hand-copied
truth table — is what is asserted.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DbSession

from app.models import User
from app.permissions import has_admin_capability, has_root_capability
from tests.factories import PASSWORD, create_admin, create_root, create_worker
from tests.probe_app import probe_app

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase1

# §7: the six §5 rows /me advertises, spelled out rather than read off
# `Capabilities.model_fields` — a stray field added to both the schema and the
# response would pass a `model_fields` comparison vacuously, but must fail here.
ADMIN_ROWS = (
    "trigger_solve",
    "override_locked_slots",
    "view_all_constraints",
    "view_audit_log",
)
ROOT_ROWS = ("manage_users", "see_root_account")
EXPECTED_KEYS = frozenset(ADMIN_ROWS + ROOT_ROWS)


def login(client: TestClient, username: str, password: str = PASSWORD) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def expected_capabilities(user: User) -> dict[str, bool]:
    """The §5 rows /me must report for `user`, derived through the predicates.

    Deliberately the *same* functions `app.deps` enforces with: this is what makes
    the assertion prove "the matrix the API enforces", not a parallel copy.
    """
    admin = has_admin_capability(user)
    root = has_root_capability(user)
    return {row: admin for row in ADMIN_ROWS} | {row: root for row in ROOT_ROWS}


def get_me(client: TestClient) -> dict[str, object]:
    response = client.get("/api/me")
    assert response.status_code == 200, response.text
    return response.json()


def test_me_capabilities_shape_is_exactly_the_six_documented_rows(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§7: /me carries a `capabilities` object holding precisely the six §5 rows.

    The two unconditional worker rows are deliberately absent (schemas.py): a
    boolean that is never false is not a signal. Asserting the exact key set pins
    both that omission and guards against a stray field appearing.
    """
    create_worker(session, "pasha")
    client = api_client_factory(probe_app)
    login(client, "pasha")

    caps = get_me(client)["capabilities"]

    assert isinstance(caps, dict)
    assert set(caps) == EXPECTED_KEYS


def test_me_capabilities_all_false_for_a_plain_worker(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5 rows 3-8 are dashes for a worker: every advertised capability is false."""
    create_worker(session, "pasha")
    client = api_client_factory(probe_app)
    login(client, "pasha")

    caps = get_me(client)["capabilities"]

    assert caps == dict.fromkeys(EXPECTED_KEYS, False)


def test_me_capabilities_for_the_admin_are_admin_true_root_false(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5: Mattia holds rows 3-6 (admin tier) but not rows 7-8 (root's alone)."""
    create_admin(session, "mattia")
    client = api_client_factory(probe_app)
    login(client, "mattia")

    caps = get_me(client)["capabilities"]

    assert all(caps[row] is True for row in ADMIN_ROWS)
    assert all(caps[row] is False for row in ROOT_ROWS)


def test_me_capabilities_for_root_are_all_true_despite_is_admin_false(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5: "Root inherits all admin capabilities" — the load-bearing case.

    Root is seeded `is_admin=false`, so this only passes if the admin rows are
    derived through `has_admin_capability` (which is true for root) and not from
    `user.is_admin`. A regression hardcoding an admin row to `is_admin` fails here.
    """
    root = create_root(session, "matteo")
    client = api_client_factory(probe_app)
    login(client, "matteo")

    caps = get_me(client)["capabilities"]

    assert root.is_admin is False
    assert caps == dict.fromkeys(EXPECTED_KEYS, True)


def test_me_capabilities_track_the_permission_predicates(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5/§7: for each tier, the reported rows equal the predicates' verdict.

    The expectation is computed from `has_admin_capability` / `has_root_capability`
    — the very functions the dependencies enforce with — so this asserts the
    advertisement and the enforcement resolve the same matrix, not two that merely
    happen to agree today.
    """
    users = {
        "pasha": create_worker(session, "pasha"),
        "mattia": create_admin(session, "mattia"),
        "matteo": create_root(session, "matteo"),
    }

    for username, user in users.items():
        client = api_client_factory(probe_app)
        login(client, username)

        caps = get_me(client)["capabilities"]

        assert caps == expected_capabilities(user), username


def test_me_never_serializes_is_root_even_for_root(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§5/§7: `is_root` never reaches the wire — not at the top level, not nested.

    MeOut is the caller's own view, so root calling /me is the case where a leak
    would be most tempting to add ("let root see its own flag"). §5 forbids it:
    root learns its status only through `capabilities.see_root_account`.
    """
    create_root(session, "matteo")
    client = api_client_factory(probe_app)
    login(client, "matteo")

    body = get_me(client)

    assert "is_root" not in body
    assert "is_root" not in body["capabilities"]
