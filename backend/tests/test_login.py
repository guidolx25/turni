"""`POST /auth/login` and its rate limiter (spec §7).

Two layers, because §7 asks for two separate things:

* `app.ratelimit.SlidingWindowRateLimiter` — "simple rate-limit on login" as a
  unit. Every test injects `now=`; nothing here sleeps, so the window arithmetic
  is exact and a loaded machine cannot change the result.
* `POST /auth/login` — the endpoint's contract: a session cookie on success, one
  indistinguishable failure for every failure mode, and 429 once the limit trips.

The endpoint tests read `settings.login_max_attempts` rather than a literal: the
threshold is configuration (§11), and a test that hardcoded 10 would quietly stop
proving anything the day it was tuned.

`api_client_factory` clears both module-level limiters around every test, so the
counters below start empty and do not leak into the next test.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.ratelimit import SlidingWindowRateLimiter
from app.routers.auth import (
    ERROR_INVALID_CREDENTIALS,
    ERROR_RATE_LIMITED,
    _ip_limiter,
    _username_limiter,
)
from app.schemas import UserOut
from tests.factories import PASSWORD, create_root, create_user, create_worker

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase1

WRONG_PASSWORD = "not-the-password"


def client_ip(index: int) -> str:
    """A distinct peer address per index.

    RFC 5737 documentation range, and deliberately not conftest's
    DEFAULT_CLIENT_IP: tests that isolate one half of the limit spread their
    failures across these so the *other* half cannot be what trips.
    """
    return f"198.51.100.{index}"


# --- the limiter as a unit (app.ratelimit) ---


def make_limiter(max_attempts: int = 3, window_seconds: int = 100) -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(max_attempts=max_attempts, window_seconds=window_seconds)


def test_limiter_is_not_limited_below_the_threshold() -> None:
    """Only the *n-th* failure locks the key; n-1 must still be allowed through."""
    limiter = make_limiter(max_attempts=3)

    for _ in range(2):
        limiter.register_failure("k", now=0.0)

    assert limiter.is_limited("k", now=0.0) is False


def test_limiter_is_limited_at_exactly_max_attempts() -> None:
    """The comparison is `>=`: the threshold is reached, not exceeded."""
    limiter = make_limiter(max_attempts=3)

    for _ in range(3):
        limiter.register_failure("k", now=0.0)

    assert limiter.is_limited("k", now=0.0) is True


def test_limiter_never_limits_a_key_with_no_failures() -> None:
    """Only failures are counted, so an untouched key is always free."""
    assert make_limiter().is_limited("never-seen", now=0.0) is False


def test_limiter_window_slides_and_old_failures_stop_counting() -> None:
    """§7's limit blunts online guessing; it must not lock an account forever."""
    limiter = make_limiter(max_attempts=3, window_seconds=100)
    for _ in range(3):
        limiter.register_failure("k", now=0.0)
    assert limiter.is_limited("k", now=0.0) is True

    assert limiter.is_limited("k", now=100.0) is False


def test_limiter_prunes_exactly_at_the_window_boundary() -> None:
    """`_prune` drops stamps with `stamp <= now - window`, so a failure is still
    counted at window-minus-epsilon and gone at exactly the window."""
    limiter = make_limiter(max_attempts=1, window_seconds=100)
    limiter.register_failure("k", now=0.0)

    assert limiter.is_limited("k", now=99.999) is True
    assert limiter.is_limited("k", now=100.0) is False


def test_limiter_expires_failures_one_at_a_time_as_the_window_slides() -> None:
    """The window is sliding, not fixed: failures age out individually rather
    than the whole bucket resetting on a tick boundary."""
    limiter = make_limiter(max_attempts=2, window_seconds=100)
    limiter.register_failure("k", now=0.0)
    limiter.register_failure("k", now=50.0)
    assert limiter.is_limited("k", now=50.0) is True

    # t=100 retires the first failure only; one remains, below the threshold.
    assert limiter.is_limited("k", now=100.0) is False
    limiter.register_failure("k", now=100.0)
    assert limiter.is_limited("k", now=100.0) is True


def test_limiter_reset_clears_one_key_and_leaves_the_others() -> None:
    """A successful login resets that key alone — it must not amnesty every
    other key the attacker is working on."""
    limiter = make_limiter(max_attempts=1)
    limiter.register_failure("a", now=0.0)
    limiter.register_failure("b", now=0.0)

    limiter.reset("a")

    assert limiter.is_limited("a", now=0.0) is False
    assert limiter.is_limited("b", now=0.0) is True


def test_limiter_reset_of_an_unknown_key_is_not_an_error() -> None:
    """`POST /auth/login` resets on every success, including the first one ever."""
    make_limiter().reset("never-seen")


def test_limiter_clear_wipes_every_key() -> None:
    """The fixture hook: without it one test's failed logins would 429 the next."""
    limiter = make_limiter(max_attempts=1)
    limiter.register_failure("a", now=0.0)
    limiter.register_failure("b", now=0.0)

    limiter.clear()

    assert limiter.is_limited("a", now=0.0) is False
    assert limiter.is_limited("b", now=0.0) is False
    assert limiter._failures == {}


def test_limiter_drops_the_dict_entry_once_a_key_empties() -> None:
    """The unbounded-growth defence, asserted on the internal it protects.

    The IP keyspace is attacker-controlled: a spray from a million addresses
    would pin a million deques in memory forever if `_prune` only emptied them.
    `_failures` is a defaultdict, so merely *reading* a key materialises an entry
    — the deletion in `_prune` is the only thing bounding the dict, and nothing
    observable from the public API would notice if it were removed.
    """
    limiter = make_limiter(max_attempts=1, window_seconds=100)
    limiter.register_failure("spray", now=0.0)
    assert "spray" in limiter._failures

    # The failure ages out; the now-empty key must not linger.
    assert limiter.is_limited("spray", now=100.0) is False
    assert "spray" not in limiter._failures


def test_limiter_query_for_an_unknown_key_does_not_materialise_an_entry() -> None:
    """Same defence, at the other door: probing unknown keys must not grow the
    dict either, even though `_failures` is a defaultdict."""
    limiter = make_limiter()

    limiter.is_limited("never-seen", now=0.0)

    assert "never-seen" not in limiter._failures


# --- the endpoint (POST /auth/login, §7) ---


def attempt(client: TestClient, username: str, password: str) -> Response:
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_login_with_the_correct_password_sets_a_session_cookie(
    client: TestClient, session: DbSession
) -> None:
    """§7: session-cookie login. The body is UserOut."""
    create_worker(session, "pasha")

    response = attempt(client, "pasha", PASSWORD)

    assert response.status_code == 200, response.text
    assert response.json()["username"] == "pasha"
    assert settings.session_cookie_name in client.cookies


def test_login_response_body_never_exposes_is_root(client: TestClient, session: DbSession) -> None:
    """§5: root is visible only to itself, and §7 says `is_root` is never
    serialized anywhere. Root logging in is the earliest chance to leak it.

    The whole key set is compared, not just `is_root`: that also catches a field
    added to the ORM row and swept into the response by a future `from_attributes`
    widening.
    """
    create_root(session, "matteo")

    response = attempt(client, "matteo", PASSWORD)

    assert response.status_code == 200, response.text
    body = response.json()
    assert "is_root" not in body
    assert set(body) == set(UserOut.model_fields)


def test_login_with_a_wrong_password_is_401(client: TestClient, session: DbSession) -> None:
    """§7: no session, and the failure is a 401 — not a 403 (which would mean
    "authenticated but not allowed")."""
    create_worker(session, "pasha")

    response = attempt(client, "pasha", WRONG_PASSWORD)

    assert response.status_code == 401
    assert response.json()["detail"] == ERROR_INVALID_CREDENTIALS
    assert settings.session_cookie_name not in client.cookies


def test_login_failures_are_indistinguishable_across_every_failure_mode(
    client: TestClient, session: DbSession
) -> None:
    """§7: no account enumeration.

    "No such user", "wrong password" and "deactivated" (§5) must be one answer.
    Any difference — status, detail, even a distinct error code — tells an
    attacker which usernames exist and which accounts are live.
    """
    create_worker(session, "pasha")
    create_user(session, "ex-worker", active=False)

    responses = {
        "unknown_username": attempt(client, "nobody", WRONG_PASSWORD),
        "wrong_password": attempt(client, "pasha", WRONG_PASSWORD),
        # Correct password, deactivated account: the only signal that could
        # separate it from the others is the one §5 forbids.
        "deactivated_user_correct_password": attempt(client, "ex-worker", PASSWORD),
    }

    for name, response in responses.items():
        assert response.status_code == 401, name
        assert response.json() == {"detail": ERROR_INVALID_CREDENTIALS}, name
        assert settings.session_cookie_name not in client.cookies, name


def test_login_is_rate_limited_after_login_max_attempts(
    client: TestClient, session: DbSession
) -> None:
    """§7: "simple rate-limit on login"."""
    create_worker(session, "pasha")

    for _ in range(settings.login_max_attempts):
        assert attempt(client, "pasha", WRONG_PASSWORD).status_code == 401

    response = attempt(client, "pasha", WRONG_PASSWORD)

    assert response.status_code == 429
    assert response.json()["detail"] == ERROR_RATE_LIMITED


def test_rate_limited_login_refuses_even_the_correct_password(
    client: TestClient, session: DbSession
) -> None:
    """Knowing the password must not buy an exemption from the limit.

    The tempting shape is to consult the limiter only on the failure path, which
    reads fine and lets the attacker's *winning* guess through — the one attempt
    where being refused actually matters. So the guarantee is that a locked key
    is refused unconditionally, correct credentials included.

    This asserts the refusal, not its position in the handler; see
    `test_rate_limited_login_does_not_reach_the_password_hasher` for the latter.
    """
    create_worker(session, "pasha")
    for _ in range(settings.login_max_attempts):
        attempt(client, "pasha", WRONG_PASSWORD)

    response = attempt(client, "pasha", PASSWORD)

    assert response.status_code == 429
    assert response.json()["detail"] == ERROR_RATE_LIMITED
    assert settings.session_cookie_name not in client.cookies


def test_rate_limited_login_does_not_reach_the_password_hasher(
    client: TestClient, session: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The limit short-circuits *before* any password work is done.

    argon2 is deliberately expensive (§7) — ~60 ms of CPU per verify. A limiter
    that returned 429 only *after* authenticating would still answer correctly
    while letting an attacker burn the box's CPU at will, turning §7's defence
    against guessing into a DoS amplifier on §11's single container.

    Status codes cannot see this (both orderings answer 429) and timing
    assertions are not deterministic, so the hasher is replaced by a landmine:
    if the handler authenticates a rate-limited request, the test explodes.
    """
    create_worker(session, "pasha")
    for _ in range(settings.login_max_attempts):
        attempt(client, "pasha", WRONG_PASSWORD)

    def landmine(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("rate-limited login must not reach argon2")

    # `_authenticate` calls the name bound in this module, so patch it there.
    monkeypatch.setattr("app.routers.auth.verify_password", landmine)

    assert attempt(client, "pasha", PASSWORD).status_code == 429


def test_successful_login_resets_the_failure_counter(
    client: TestClient, session: DbSession
) -> None:
    """A legitimate user who mistypes occasionally must never accumulate toward
    the limit across a 15-minute window they also logged in during."""
    create_worker(session, "pasha")

    for _ in range(settings.login_max_attempts - 1):
        assert attempt(client, "pasha", WRONG_PASSWORD).status_code == 401
    assert attempt(client, "pasha", PASSWORD).status_code == 200

    # Without the reset this next failure would be the max-th and lock the key.
    assert attempt(client, "pasha", WRONG_PASSWORD).status_code == 401
    assert attempt(client, "pasha", PASSWORD).status_code == 200


def test_username_rate_limit_key_is_case_folded(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """`login` keys the username limiter on `.casefold()`, so varying the case
    must not buy an attacker a fresh bucket per spelling.

    Each failure comes from its own IP so that the per-IP limiter cannot be what
    trips — this test must fail if the casefold is removed, and for no other
    reason.
    """
    create_worker(session, "pasha")
    spellings = ("Pasha", "pasha", "PASHA", "pAsHa")

    for index in range(settings.login_max_attempts):
        client = api_client_factory(ip=client_ip(index))
        assert attempt(client, spellings[index % len(spellings)], WRONG_PASSWORD).status_code == 401

    fresh = api_client_factory(ip=client_ip(200))
    assert attempt(fresh, "pasha", PASSWORD).status_code == 429


def test_username_limit_trips_independently_of_the_ip(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§7: per-IP alone would let a distributed attacker hammer one account —
    one attempt per host, no host ever reaching its own limit."""
    create_worker(session, "pasha")

    for index in range(settings.login_max_attempts):
        botnet_host = api_client_factory(ip=client_ip(index))
        assert attempt(botnet_host, "pasha", WRONG_PASSWORD).status_code == 401

    # A host that has never failed: the username's own counter is what refuses.
    fresh = api_client_factory(ip=client_ip(200))
    assert attempt(fresh, "pasha", PASSWORD).status_code == 429


def test_ip_limit_trips_independently_of_the_username(
    api_client_factory: Callable[..., TestClient], session: DbSession
) -> None:
    """§7: per-username alone would let one host spray a single attempt at every
    account — no username ever reaching its own limit."""
    create_worker(session, "pasha")
    attacker = api_client_factory(ip=client_ip(1))

    for index in range(settings.login_max_attempts):
        assert attempt(attacker, f"victim{index}", WRONG_PASSWORD).status_code == 401

    # `pasha` has zero failures of its own; the attacker's IP is what refuses.
    assert attempt(attacker, "pasha", PASSWORD).status_code == 429

    # ...and the refusal is keyed on the IP, not global: another host is fine.
    bystander = api_client_factory(ip=client_ip(2))
    assert attempt(bystander, "pasha", PASSWORD).status_code == 200


def test_the_endpoint_limiters_are_configured_from_settings() -> None:
    """§11: the threshold and window are config, not constants buried in the
    handler. The tests above exercise the wiring; this names it."""
    for limiter in (_username_limiter, _ip_limiter):
        assert limiter._max_attempts == settings.login_max_attempts
        assert limiter._window_seconds == settings.login_window_seconds
