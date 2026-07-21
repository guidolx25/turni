"""Password hashing and cookie signing (spec §7).

Two independent primitives live here because both are pure functions over
secrets and neither should be reachable from a request handler directly:
handlers go through `app.sessions` / `app.routers.auth`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import settings

# §7: argon2. Library defaults are argon2id with the current RFC 9106-flavoured
# parameters; pinning our own numbers here would freeze them at today's hardware.
_hasher = PasswordHasher()

# A floor the spec does not set. It lives HERE, not in a router, because two
# routes now set passwords — the §7 self-service change on `/me/settings` and the
# §5 root reset/create on `/root/users` — and a policy that differed between them
# would mean the weaker route defines the system's real minimum.
MIN_PASSWORD_LENGTH = 8
# Machine code, not prose (§9 keeps user-visible strings in the dictionaries).
# Shared for the same reason as the length: one failure, one key to render.
ERROR_PASSWORD_TOO_SHORT = "new_password_too_short"


def password_too_short(password: str) -> bool:
    """Is `password` below the shared §7 floor? Pure — the caller raises."""
    return len(password) < MIN_PASSWORD_LENGTH


def hash_password(password: str) -> str:
    """Hash a plaintext password for `users.password_hash` (§6)."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-ish-time verify. False for a wrong password *and* for a hash we
    cannot parse — a corrupt hash must not authenticate anyone."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True when the stored hash was made with weaker parameters than current.

    Callers re-hash transparently on a successful login: the plaintext is only
    in hand at that moment.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        # Unparseable: not "needs rehash", it needs an admin password reset.
        return False


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """A throwaway hash to verify against when the username does not exist.

    §7: without this, a login for an unknown user returns in microseconds while a
    known user costs a full argon2 verify, and the difference enumerates accounts.
    Cached because computing it is deliberately expensive.
    """
    return _hasher.hash(secrets.token_urlsafe(32))


def new_ics_token() -> str:
    """A fresh §7 `/export/ics` feed credential (§6 users.ics_token, v1.7).

    Per-user, random, opaque — never derived from identity or SECRET_KEY, so one
    leaked calendar URL is revoked by regenerating ONE user's token, never by a
    key rotation that logs everybody out."""
    return secrets.token_urlsafe(32)


def _signature(value: str) -> str:
    digest = hmac.new(settings.secret_key.encode(), value.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def sign_token(token: str) -> str:
    """§7: the cookie carries a *signed* session token.

    The token is already an unguessable server-side lookup key; the signature
    means forged or truncated cookies are rejected by HMAC rather than by a
    database round-trip, so garbage never reaches the session table.
    """
    return f"{token}.{_signature(token)}"


def unsign_token(signed: str) -> str | None:
    """Recover the token from a signed cookie value, or None if it does not
    verify. Never logs or echoes the value: it is a credential."""
    token, separator, signature = signed.rpartition(".")
    if not separator or not token:
        return None
    if not hmac.compare_digest(signature, _signature(token)):
        return None
    return token
