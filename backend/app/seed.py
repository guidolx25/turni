"""Seed the accounts from spec §1/§5.  Run: `uv run python -m app.seed`

§5: "No public signup" — this script and root's user management are the only
ways an account comes into existence.

Per §5's build decision ("single account with `is_root` flag"), Matteo is one row
holding worker + root rather than two accounts, so the table below has five rows.

Passwords come from the environment, one variable per account:

    SEED_PASSWORD_MATTEO, SEED_PASSWORD_FRANCESCO, SEED_PASSWORD_PASHA,
    SEED_PASSWORD_AMIR, SEED_PASSWORD_MATTIA

Any that are unset get a freshly generated random password, printed once. There
is no default password: a fallback constant here would be a published credential
on every deployment that forgot to set the env var.

Idempotent: an account that already exists is left completely untouched —
including its password, which by then is the user's, not the seed's.
"""

from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass
from typing import TextIO

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db import SessionLocal
from app.enums import UserRole
from app.models import User
from app.security import hash_password

# Generated passwords are shown once and never stored in plaintext; long enough
# that the one-time print is not the weak link.
_GENERATED_PASSWORD_BYTES = 16


@dataclass(frozen=True)
class SeedAccount:
    """One row of §1's people table."""

    username: str
    display_name: str
    role: UserRole
    is_admin: bool = False
    is_root: bool = False


# §1 people table + §5 system roles.
SEED_ACCOUNTS: tuple[SeedAccount, ...] = (
    # Matteo: worker + hidden root. Root inherits all admin capabilities (§5),
    # so is_admin stays false — the capability comes from is_root, and setting
    # both would imply two independent sources of admin authority.
    SeedAccount("matteo", "Matteo", UserRole.BAGNINO, is_root=True),
    SeedAccount("francesco", "Francesco", UserRole.BAGNINO),
    SeedAccount("pasha", "Pasha", UserRole.SPIAGGINO),
    SeedAccount("amir", "Amir", UserRole.SPIAGGINO),
    # Mattia: jolly (both roles, H6) + the visible admin.
    SeedAccount("mattia", "Mattia", UserRole.JOLLY, is_admin=True),
)


def password_env_var(username: str) -> str:
    """Env var name carrying `username`'s seed password."""
    return f"SEED_PASSWORD_{username.upper()}"


def _resolve_password(account: SeedAccount) -> tuple[str, bool]:
    """Return (password, was_generated) for an account."""
    from_env = os.environ.get(password_env_var(account.username))
    if from_env:
        return from_env, False
    return secrets.token_urlsafe(_GENERATED_PASSWORD_BYTES), True


def seed_accounts(db: DbSession, *, out: TextIO = sys.stdout) -> list[User]:
    """Create any missing §5 account. Returns the rows created (possibly none)."""
    created: list[User] = []
    for account in SEED_ACCOUNTS:
        existing = db.scalars(select(User).where(User.username == account.username)).one_or_none()
        if existing is not None:
            print(f"exists, unchanged: {account.username}", file=out)
            continue

        password, was_generated = _resolve_password(account)
        user = User(
            username=account.username,
            password_hash=hash_password(password),
            display_name=account.display_name,
            role=account.role,
            is_admin=account.is_admin,
            is_root=account.is_root,
            # §6 leaves email nullable and §10 makes the email channel opt-out;
            # addresses are set by the user in settings, not guessed here.
            email=None,
        )
        db.add(user)
        created.append(user)

        if was_generated:
            # The only time this password is ever legible. Not logged: it must
            # not end up in §11's structured log stream.
            print(f"created: {account.username} — generated password: {password}", file=out)
        else:
            print(
                f"created: {account.username} — password from "
                f"{password_env_var(account.username)}",
                file=out,
            )

    db.commit()
    return created


def main() -> None:
    with SessionLocal() as db:
        created = seed_accounts(db)
    print(f"\n{len(created)} account(s) created, {len(SEED_ACCOUNTS) - len(created)} left alone.")


if __name__ == "__main__":
    main()
