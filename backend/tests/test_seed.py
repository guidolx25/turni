"""The seed script (spec §1 people table, §5 accounts).

§5 decides this: "5 workers + root ... single account with `is_root` flag ...
that decision makes it 5 account rows, not 6". And "No public signup" — this
script plus root's user management are the only ways an account exists, which
makes the seed part of the security surface rather than a convenience.

Two properties carry the weight here:

* **Idempotence.** The script is re-run on every deploy. By the second run the
  stored password is the *user's*, not the seed's, so re-hashing "just to be
  safe" would silently reset five people's credentials on a routine deploy.
* **No default password.** A constant fallback would be a published credential on
  every deployment that forgot an env var. Tests below prove two accounts in one
  run, and the same account across two deployments, get different secrets.

`out` is a StringIO throughout: the generated password is printed exactly once
and never persisted, so the print stream is the only place to observe it.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.enums import UserRole
from app.models import User
from app.security import verify_password
from app.seed import SEED_ACCOUNTS, password_env_var, seed_accounts

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase1

# The exact strings seed.py prints. Parsed rather than eyeballed because the
# generated password is legible in precisely one place and never again.
GENERATED_RE = re.compile(r"^created: (?P<username>\S+) — generated password: (?P<password>.+)$")
FROM_ENV_RE = re.compile(r"^created: (?P<username>\S+) — password from (?P<var>\S+)$")
UNCHANGED_RE = re.compile(r"^exists, unchanged: (?P<username>\S+)$")


@pytest.fixture(autouse=True)
def no_seed_passwords(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset every `SEED_PASSWORD_*` var.

    A developer with `SEED_PASSWORD_MATTEO` exported would otherwise turn the
    "generates a random password" tests into no-ops that pass.
    """
    for account in SEED_ACCOUNTS:
        monkeypatch.delenv(password_env_var(account.username), raising=False)


def run_seed(db: DbSession) -> tuple[list[User], str]:
    """Seed `db`, returning the created rows and everything the script printed."""
    out = io.StringIO()
    created = seed_accounts(db, out=out)
    return created, out.getvalue()


def parse(pattern: re.Pattern[str], output: str) -> dict[str, re.Match[str]]:
    """Every line of `output` matching `pattern`, keyed by username."""
    matches = (pattern.match(line) for line in output.splitlines())
    return {match["username"]: match for match in matches if match is not None}


def usernames(db: DbSession) -> set[str]:
    """A set, not a list: the seeded identities are the claim, and SQLite's
    collation order is not something §1 has an opinion about."""
    return set(db.scalars(select(User.username)).all())


def get_user(db: DbSession, username: str) -> User:
    return db.scalars(select(User).where(User.username == username)).one()


# --- the §1 people table, as §5's five rows ---


def test_seed_creates_the_five_accounts_of_the_people_table(session: DbSession) -> None:
    """§1's table: Matteo, Francesco, Pasha, Amir, Mattia — and nobody else."""
    created, _ = run_seed(session)

    assert len(created) == 5
    assert usernames(session) == {"matteo", "francesco", "pasha", "amir", "mattia"}


def test_seed_creates_five_rows_not_six(session: DbSession) -> None:
    """§5: "single account with `is_root` flag ... makes it 5 account rows, not
    6". A separate root row would be the other, rejected, build decision."""
    run_seed(session)

    assert session.scalar(select(func.count()).select_from(User)) == 5


def test_seed_assigns_the_roles_from_the_people_table(session: DbSession) -> None:
    """§1: two bagnini, two spiaggini, and Mattia the jolly (both roles, H6)."""
    run_seed(session)

    roles = {user.username: user.role for user in session.scalars(select(User)).all()}

    assert roles == {
        "matteo": UserRole.BAGNINO,
        "francesco": UserRole.BAGNINO,
        "pasha": UserRole.SPIAGGINO,
        "amir": UserRole.SPIAGGINO,
        "mattia": UserRole.JOLLY,
    }


def test_seed_makes_matteo_one_account_holding_worker_and_root(session: DbSession) -> None:
    """§1/§5: Matteo is worker + hidden root in a single row.

    `is_admin` must be *false*: §5 says root "inherits all admin capabilities",
    so the authority comes from `is_root` alone. Setting both flags would imply
    two independent sources of admin authority, and revoking `is_root` would
    leave a silently-still-admin account behind.
    """
    run_seed(session)

    matteo = get_user(session, "matteo")

    assert matteo.is_root is True
    assert matteo.is_admin is False
    assert matteo.role is UserRole.BAGNINO
    assert matteo.active is True


def test_seed_creates_exactly_one_root_account(session: DbSession) -> None:
    """§5: root is a single hidden account. A second one would be a second
    invisible superuser — and invisible is exactly what makes that dangerous."""
    run_seed(session)

    roots = session.scalars(select(User).where(User.is_root)).all()

    assert [user.username for user in roots] == ["matteo"]


def test_seed_makes_mattia_the_only_visible_admin(session: DbSession) -> None:
    """§1/§5: Mattia is the visible admin; §5 gives no other account `is_admin`."""
    run_seed(session)

    admins = session.scalars(select(User).where(User.is_admin)).all()

    assert [user.username for user in admins] == ["mattia"]
    assert admins[0].is_root is False


def test_seed_leaves_email_unset(session: DbSession) -> None:
    """§6 leaves email nullable and §10 makes the email channel opt-out: an
    address guessed here would send real mail to whoever owns the guess."""
    run_seed(session)

    assert all(user.email is None for user in session.scalars(select(User)).all())


# --- idempotence ---


def test_seed_run_twice_creates_nothing_the_second_time(session: DbSession) -> None:
    """The script runs on every deploy; the second run must be a no-op."""
    run_seed(session)

    created, output = run_seed(session)

    assert created == []
    assert session.scalar(select(func.count()).select_from(User)) == 5
    assert set(parse(UNCHANGED_RE, output)) == {acc.username for acc in SEED_ACCOUNTS}


def test_seed_run_twice_leaves_existing_password_hashes_byte_identical(
    session: DbSession,
) -> None:
    """The highest-value assertion in this file.

    By the second deploy the stored hash is the *user's* password, not the
    seed's. Re-hashing — even to the same plaintext — would lock five people out,
    and argon2's random salt means the new hash would not even be comparable. So
    the check is byte-identity, not "still verifies".

    The hash is deliberately replaced first, standing in for a user who has since
    changed their password: identity against the seed's own hash could pass by
    accident, identity against a *foreign* hash cannot.
    """
    run_seed(session)
    for user in session.scalars(select(User)).all():
        user.password_hash = f"argon2-set-by-the-user-{user.username}"
    session.commit()
    before = {user.username: user.password_hash for user in session.scalars(select(User)).all()}

    run_seed(session)

    after = {user.username: user.password_hash for user in session.scalars(select(User)).all()}
    assert after == before


def test_seed_run_twice_leaves_every_field_of_an_existing_row_untouched(
    session: DbSession,
) -> None:
    """ "An account that already exists is left completely untouched" — including
    the fields the user owns. Re-asserting the seed's values would undo a
    language choice or, worse, silently reactivate a §5-deactivated account."""
    run_seed(session)
    mattia = get_user(session, "mattia")
    mattia.display_name = "Mattia (jolly)"
    mattia.email = "mattia@example.test"
    mattia.email_notifications = False
    mattia.active = False
    session.commit()

    run_seed(session)

    session.expire_all()
    reloaded = get_user(session, "mattia")
    assert reloaded.display_name == "Mattia (jolly)"
    assert reloaded.email == "mattia@example.test"
    assert reloaded.email_notifications is False
    assert reloaded.active is False


def test_seed_fills_in_only_the_missing_accounts(session: DbSession) -> None:
    """A partially-seeded database — e.g. an account root deleted before §5
    settled on deactivation — must be completed, not duplicated or refused."""
    run_seed(session)
    session.delete(get_user(session, "amir"))
    session.commit()

    created, output = run_seed(session)

    assert [user.username for user in created] == ["amir"]
    assert len(usernames(session)) == 5
    assert "amir" in usernames(session)
    assert set(parse(UNCHANGED_RE, output)) == {"matteo", "francesco", "pasha", "mattia"}


# --- passwords (§5: no public signup, therefore no published credential) ---


def test_seed_takes_a_password_from_the_accounts_env_var(
    session: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One variable per account, `SEED_PASSWORD_<USERNAME>`."""
    monkeypatch.setenv(password_env_var("pasha"), "il-segreto-di-pasha-9271")

    run_seed(session)

    assert verify_password(get_user(session, "pasha").password_hash, "il-segreto-di-pasha-9271")


def test_seed_generates_a_password_when_the_env_var_is_unset(session: DbSession) -> None:
    """No default constant: an unset variable yields a fresh random secret."""
    _, output = run_seed(session)

    generated = parse(GENERATED_RE, output)

    assert set(generated) == {acc.username for acc in SEED_ACCOUNTS}
    for username, match in generated.items():
        assert verify_password(get_user(session, username).password_hash, match["password"])


def test_seed_generates_a_different_password_for_every_account(session: DbSession) -> None:
    """If two accounts in one run shared a secret it would be a constant, however
    randomly it was chosen."""
    _, output = run_seed(session)

    passwords = {match["password"] for match in parse(GENERATED_RE, output).values()}

    assert len(passwords) == len(SEED_ACCOUNTS)


def test_seed_generates_a_different_password_on_every_deployment(
    fresh_session: Callable[[], DbSession],
) -> None:
    """The decisive "no default password" test: §5 has no public signup, so a
    fallback constant here would be *the* credential on every deployment that
    forgot the env var — and it would be readable in this repository.

    Two virgin databases stand in for two deployments. A hardcoded default would
    make these identical; nothing else would.
    """
    _, first = run_seed(fresh_session())
    _, second = run_seed(fresh_session())

    first_passwords = {u: m["password"] for u, m in parse(GENERATED_RE, first).items()}
    second_passwords = {u: m["password"] for u, m in parse(GENERATED_RE, second).items()}

    assert set(first_passwords) == set(second_passwords) != set()
    for username, password in first_passwords.items():
        assert password != second_passwords[username], username


def test_seed_prints_a_generated_password_exactly_once(session: DbSession) -> None:
    """It is unrecoverable afterwards, so it must be shown — but a second echo
    doubles the number of places it can be shoulder-surfed or scrolled back to."""
    _, output = run_seed(session)

    for match in parse(GENERATED_RE, output).values():
        assert output.count(match["password"]) == 1


def test_seed_never_prints_a_password_supplied_by_the_environment(
    session: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The operator already knows it. Echoing it only copies a live credential
    into deploy logs and terminal scrollback for no benefit — the variable name
    is all the confirmation that is needed."""
    secret = "il-segreto-di-pasha-9271"
    monkeypatch.setenv(password_env_var("pasha"), secret)

    _, output = run_seed(session)

    assert secret not in output
    assert parse(FROM_ENV_RE, output)["pasha"]["var"] == "SEED_PASSWORD_PASHA"
    # ...and it must not be smuggled out through the generated-password line.
    assert "pasha" not in parse(GENERATED_RE, output)


def test_seed_stores_no_password_in_plaintext(session: DbSession, db_path: Path) -> None:
    """§6 stores `password_hash`, and §7 says argon2. The database *file* is
    searched rather than the column: a plaintext copy landing in any other column
    would be just as fatal and would sail past a per-column assertion.
    """
    _, output = run_seed(session)
    session.commit()

    blob = db_path.read_bytes()
    for match in parse(GENERATED_RE, output).values():
        assert match["password"].encode() not in blob, match["username"]


def test_every_seeded_password_verifies_against_the_stored_hash(session: DbSession) -> None:
    """End to end: what the script prints is what `POST /auth/login` (§7) will
    accept. A hash of the wrong string is indistinguishable from a good one until
    somebody tries to log in."""
    _, output = run_seed(session)

    generated = parse(GENERATED_RE, output)
    for user in session.scalars(select(User)).all():
        assert verify_password(user.password_hash, generated[user.username]["password"])
        assert user.password_hash != generated[user.username]["password"]
