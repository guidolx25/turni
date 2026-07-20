"""Password hashing and cookie signing (spec §7).

§7 asks for two primitives by name: `argon2` password hashing, and a *signed*
session cookie. These tests pin both at the level where they are pure functions
over a secret — no database, no request.
"""

from __future__ import annotations

import pytest
from argon2 import PasswordHasher

from app.config import settings
from app.security import (
    dummy_password_hash,
    hash_password,
    password_needs_rehash,
    sign_token,
    unsign_token,
    verify_password,
)

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase1

PASSWORD = "una-password-piuttosto-lunga"

# Deliberately far below the library defaults, to stand in for a hash written by
# an older deployment. `memory_cost` must stay >= 8 * parallelism.
_WEAK_HASHER = PasswordHasher(time_cost=1, memory_cost=64, parallelism=1)


def test_hash_password_uses_argon2_and_salts_every_hash() -> None:
    """§7: argon2 password hashing."""
    first = hash_password(PASSWORD)
    second = hash_password(PASSWORD)

    assert first.startswith("$argon2")
    # Same plaintext, different digest: a per-hash salt is present, so the column
    # cannot be scanned for users sharing a password.
    assert first != second
    assert verify_password(first, PASSWORD) is True
    assert verify_password(second, PASSWORD) is True


def test_verify_password_rejects_a_wrong_password() -> None:
    assert verify_password(hash_password(PASSWORD), PASSWORD + "x") is False
    assert verify_password(hash_password(PASSWORD), "") is False


def test_verify_password_rejects_an_unparseable_hash() -> None:
    """A corrupt `users.password_hash` must authenticate nobody, not raise."""
    for corrupt in ("", "not-a-hash", "$argon2id$v=19$garbage"):
        assert verify_password(corrupt, PASSWORD) is False


def test_password_needs_rehash_is_false_for_a_current_hash() -> None:
    assert password_needs_rehash(hash_password(PASSWORD)) is False


def test_password_needs_rehash_is_true_for_weaker_parameters() -> None:
    """The transparent-upgrade path: a hash made with older, cheaper parameters
    is flagged so a successful login can replace it."""
    assert password_needs_rehash(_WEAK_HASHER.hash(PASSWORD)) is True


def test_password_needs_rehash_is_false_for_an_unparseable_hash() -> None:
    """Unparseable is not "needs rehash": there is no plaintext to re-hash it
    from, and claiming otherwise would make a login attempt rewrite garbage."""
    assert password_needs_rehash("not-a-hash") is False


def test_dummy_password_hash_is_verifiable_and_matches_nothing() -> None:
    """§7: the constant-cost path for an unknown username.

    It must be a *real* argon2 hash, so verifying against it costs the same as
    verifying a real user, and it must never accept a password.
    """
    dummy = dummy_password_hash()

    assert dummy.startswith("$argon2")
    assert verify_password(dummy, PASSWORD) is False
    assert verify_password(dummy, "") is False


def test_dummy_password_hash_is_cached() -> None:
    """Cached deliberately: recomputing an argon2 hash per unknown-user login
    would make the enumeration defence cost more than the thing it defends."""
    assert dummy_password_hash() is dummy_password_hash()


def test_sign_token_round_trips() -> None:
    """§7: the cookie carries a signed token; the server must get it back."""
    token = "AbC-123_token"
    signed = sign_token(token)

    assert signed != token
    assert signed.startswith(f"{token}.")
    assert unsign_token(signed) == token


def test_sign_token_round_trips_a_token_containing_a_dot() -> None:
    """The separator is the *last* dot, so a token containing one survives."""
    assert unsign_token(sign_token("a.b.c")) == "a.b.c"


def test_unsign_token_rejects_a_tampered_payload() -> None:
    signed = sign_token("token-one")
    _, _, signature = signed.rpartition(".")

    assert unsign_token(f"token-two.{signature}") is None


def test_unsign_token_rejects_a_tampered_signature() -> None:
    signed = sign_token("token-one")
    flipped = signed[:-1] + ("A" if signed[-1] != "A" else "B")

    assert unsign_token(flipped) is None


def test_unsign_token_rejects_a_truncated_cookie() -> None:
    signed = sign_token("token-one")

    assert unsign_token(signed[: len(signed) // 2]) is None
    assert unsign_token(signed.rpartition(".")[0]) is None


def test_unsign_token_rejects_an_unsigned_or_empty_value() -> None:
    """No separator at all, or an empty payload: never a valid cookie."""
    assert unsign_token("token-with-no-signature") is None
    assert unsign_token("") is None
    assert unsign_token(".signature") is None


def test_signature_is_bound_to_the_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cookie signed under one SECRET_KEY must not verify under another —
    otherwise rotating the key (§11 config) would not revoke anything."""
    signed = sign_token("token-one")
    assert unsign_token(signed) == "token-one"

    monkeypatch.setattr(settings, "secret_key", "a-completely-different-key-0123456789")

    assert unsign_token(signed) is None
