"""§11 config: `SECRET_KEY` must fail loudly in prod.

`DEV_INSECURE_SECRET_KEY` is a constant published in this repository. If a prod
deploy that forgot to set `SECRET_KEY` fell back to it, every real session cookie
would be signed (`app.security.sign_token`) with a value any reader of the source
can forge. So the interesting assertion here is not "prod wants a key" but "prod
refuses *this* key" — the rest of §7's session auth rests on it.

`Settings` reads the process environment and a `.env` file. Every instance below
is built hermetically (`_env_file=None` + the `hermetic_env` fixture) so that a
developer's ambient `SECRET_KEY`, or a `.env` sitting in the backend directory,
can neither rescue a test that should fail nor break one that should pass.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.config import (
    DEV_INSECURE_SECRET_KEY,
    MIN_SECRET_KEY_LENGTH,
    Environment,
    Settings,
)

# 43 chars, the shape `secrets.token_urlsafe(32)` produces — what §11 expects an
# operator to actually put in the environment.
REAL_SECRET_KEY = "Ck9nQ2ZUcXpZbVJ2S3hMd1B0TmhHZFNqQWJFdVh5Zg"


@pytest.fixture
def hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every env var `Settings` reads, so each test states its own world.

    Without this, `ENV`/`SECRET_KEY` exported in a developer's shell (or by CI)
    would silently supply the very values under test.
    """
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
        monkeypatch.delenv(field, raising=False)


def build(**overrides: Any) -> Settings:
    """A `Settings` built from `overrides` alone — no `.env`, no environment."""
    return Settings(_env_file=None, **overrides)


# --- prod refuses to boot without a real key ---


@pytest.mark.usefixtures("hermetic_env")
def test_prod_without_a_secret_key_refuses_to_start() -> None:
    """§11: a misconfigured prod deploy must crash, not sign cookies with a
    default. Pydantic wraps the validator's ValueError in a ValidationError."""
    with pytest.raises(ValidationError) as exc:
        build(env=Environment.PROD)

    assert "SECRET_KEY is required" in str(exc.value)


@pytest.mark.usefixtures("hermetic_env")
def test_prod_rejects_an_empty_secret_key() -> None:
    """An explicitly empty value is "unset", not "a key of length zero"."""
    with pytest.raises(ValidationError):
        build(env=Environment.PROD, secret_key="")


@pytest.mark.usefixtures("hermetic_env")
def test_prod_rejects_the_published_development_secret_key() -> None:
    """The load-bearing one: this constant is in the repo, so accepting it in
    prod would hand session forgery to anyone who can read the source.

    The message is asserted because a bare `raises` here would also pass on the
    length check below — this must be refused for being *the dev default*, and
    would stay refused if the constant were ever lengthened.
    """
    with pytest.raises(ValidationError) as exc:
        build(env=Environment.PROD, secret_key=DEV_INSECURE_SECRET_KEY)

    assert "must not be the development default" in str(exc.value)


@pytest.mark.usefixtures("hermetic_env")
def test_prod_rejects_a_secret_key_below_the_minimum_length() -> None:
    """§11: below `MIN_SECRET_KEY_LENGTH` the HMAC key is not worth signing with."""
    with pytest.raises(ValidationError) as exc:
        build(env=Environment.PROD, secret_key="x" * (MIN_SECRET_KEY_LENGTH - 1))

    assert f"at least {MIN_SECRET_KEY_LENGTH}" in str(exc.value)


@pytest.mark.usefixtures("hermetic_env")
def test_prod_accepts_a_secret_key_of_exactly_the_minimum_length() -> None:
    """The boundary is inclusive: `>= MIN_SECRET_KEY_LENGTH` is acceptable."""
    key = "x" * MIN_SECRET_KEY_LENGTH

    assert build(env=Environment.PROD, secret_key=key).secret_key == key


@pytest.mark.usefixtures("hermetic_env")
def test_prod_keeps_a_real_secret_key_verbatim() -> None:
    """The validator must not normalise, trim or regenerate the operator's key:
    a mutated key invalidates every session cookie already issued."""
    assert build(env=Environment.PROD, secret_key=REAL_SECRET_KEY).secret_key == REAL_SECRET_KEY


# --- dev stays ergonomic ---


@pytest.mark.usefixtures("hermetic_env")
def test_dev_is_the_default_environment() -> None:
    """A bare checkout must run without an env file (§11 dev ergonomics)."""
    assert build().env is Environment.DEV


@pytest.mark.usefixtures("hermetic_env")
def test_dev_without_a_secret_key_falls_back_to_the_insecure_default() -> None:
    """The fallback exists so `uv run uvicorn` works on a fresh clone; it is
    exactly what prod refuses above."""
    settings = build(env=Environment.DEV)

    assert settings.secret_key == DEV_INSECURE_SECRET_KEY


@pytest.mark.usefixtures("hermetic_env")
def test_dev_keeps_an_explicit_secret_key() -> None:
    """The fallback only fills an *unset* key — it never overwrites a real one,
    or a dev pointing at a staging database would sign with the wrong secret."""
    settings = build(env=Environment.DEV, secret_key=REAL_SECRET_KEY)

    assert settings.secret_key == REAL_SECRET_KEY


@pytest.mark.usefixtures("hermetic_env")
def test_dev_accepts_a_short_secret_key() -> None:
    """The length floor is a prod rule: enforcing it in dev would break nothing
    real and annoy everyone."""
    assert build(env=Environment.DEV, secret_key="short").secret_key == "short"


# --- cookie_secure (§7) ---


@pytest.mark.usefixtures("hermetic_env")
def test_cookie_secure_is_false_in_dev() -> None:
    """§7: local dev has no TLS to carry a `Secure` cookie, so login would break."""
    assert build(env=Environment.DEV).cookie_secure is False


@pytest.mark.usefixtures("hermetic_env")
def test_cookie_secure_is_true_in_prod() -> None:
    """§7 + §11: production runs TLS; the session cookie must not travel clear."""
    assert build(env=Environment.PROD, secret_key=REAL_SECRET_KEY).cookie_secure is True
