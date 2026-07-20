"""Shared fixtures for the schema (§6) and auth (§5/§7) suites.

Two things this module guarantees before anything else imports `app`:

1. `DATABASE_URL` points at a throwaway file. `app.db` builds its engine at
   import time from `app.config.settings`; without this the suite would be one
   stray `create_all` away from writing to the dev database.
2. Every schema fixture is built by running the *migration*, not
   `Base.metadata.create_all`. The migration is what production runs, so it is
   what the tests must interrogate; `test_migration.py::test_alembic_check_*`
   separately proves models and migration agree.

The migrated schema is built once per session into a template file and copied
per test, so each test gets an isolated, function-scoped database while paying
the alembic cost only once.

The HTTP fixtures exist because `app.db.engine` is bound at import time to that
empty scratch file: a TestClient is only useful once `get_session` is overridden
with the test's own migrated Session, which `api_client_factory` does.
"""

from __future__ import annotations

import itertools
import logging
import os
import shutil
import tempfile
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Set before `app.config` is imported anywhere: protects the dev database.
_SCRATCH = Path(tempfile.mkdtemp(prefix="turni-test-session-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_SCRATCH / 'session.db'}"

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Connection, Engine, create_engine, event, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from alembic import command  # noqa: E402

# A stable, obviously-fake peer address. Tests that care about the per-IP half of
# the login rate limit (§7) pass their own.
DEFAULT_CLIENT_IP = "203.0.113.10"


def alembic_config(url: str) -> Config:
    """An alembic Config bound to `url`.

    `alembic/env.py` overrides the URL from `app.config.settings`, so the
    setting has to move too — see `database_url`.
    """
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@contextmanager
def database_url(url: str) -> Iterator[None]:
    """Point `settings.database_url` (and therefore `alembic/env.py`) at `url`."""
    from app.config import settings

    previous = settings.database_url
    settings.database_url = url
    try:
        yield
    finally:
        settings.database_url = previous


@pytest.fixture(autouse=True)
def _app_loggers_enabled() -> None:
    """Undo the collateral damage `alembic/env.py` does to logging.

    `env.py` calls `logging.config.fileConfig(alembic.ini)`, which defaults to
    `disable_existing_loggers=True` and therefore sets `disabled = True` on every
    logger that already exists — including all of `app.*`. Any alembic run
    (`run_upgrade`, `run_downgrade`, `command.check`) silences the application's
    loggers for the REST OF THE SESSION, because the schema template is built once
    per session and `test_migration` runs more migrations besides.

    The effect is that log-based assertions pass vacuously: nothing is ever
    captured, so "the expected error was logged" and "no error was logged" are
    indistinguishable. Autouse and function-scoped so no ordering between a
    migration test and a logging test can reintroduce it.
    """
    for lg in logging.root.manager.loggerDict.values():
        if isinstance(lg, logging.Logger) and lg.name.startswith("app"):
            lg.disabled = False


def run_upgrade(url: str, revision: str = "head") -> None:
    with database_url(url):
        command.upgrade(alembic_config(url), revision)


def run_downgrade(url: str, revision: str = "base") -> None:
    with database_url(url):
        command.downgrade(alembic_config(url), revision)


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def make_engine(path: Path) -> Engine:
    """An engine with SQLite's per-connection FK pragma actually enabled.

    `PRAGMA foreign_keys` is off by default and is per *connection*, so an FK
    test on a bare engine passes vacuously. `app.db` installs this listener on
    the application engine only; test engines must install their own.
    """
    engine = create_engine(sqlite_url(path), future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


@pytest.fixture(scope="session")
def migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A database at head, built once, copied by `db_path` for each test."""
    path = tmp_path_factory.mktemp("schema-template") / "head.db"
    run_upgrade(sqlite_url(path))
    return path


@pytest.fixture
def db_path(migrated_template: Path, tmp_path: Path) -> Path:
    """A private copy of the migrated schema, one per test."""
    path = tmp_path / "turni.db"
    shutil.copyfile(migrated_template, path)
    return path


@pytest.fixture
def engine(db_path: Path) -> Generator[Engine, None, None]:
    eng = make_engine(db_path)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def connection(engine: Engine) -> Generator[Connection, None, None]:
    """A raw connection — used to insert past the ORM's type layer, so that the
    assertion lands on the DDL's CHECK constraint rather than on Python."""
    with engine.connect() as conn:
        # Guard against the vacuous-FK-test trap: prove the pragma took.
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        yield conn


@pytest.fixture
def session(engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
    with factory() as sess:
        yield sess


@pytest.fixture
def fresh_session(
    migrated_template: Path, tmp_path: Path
) -> Generator[Callable[[], Session], None, None]:
    """Build additional, independent migrated databases on demand.

    For the few tests that must compare two separate deployments — e.g. proving
    the seed script generates a *different* password each time it runs against a
    virgin database (§5: no default credential).
    """
    engines: list[Engine] = []
    sessions: list[Session] = []
    counter = itertools.count()

    def factory() -> Session:
        path = tmp_path / f"fresh-{next(counter)}.db"
        shutil.copyfile(migrated_template, path)
        eng = make_engine(path)
        engines.append(eng)
        sess = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False, future=True)()
        sessions.append(sess)
        return sess

    try:
        yield factory
    finally:
        for sess in sessions:
            sess.close()
        for eng in engines:
            eng.dispose()


@pytest.fixture
def api_client_factory(session: Session) -> Generator[Callable[..., TestClient], None, None]:
    """TestClients that talk to this test's migrated database.

    Two process-global pieces of state have to be handled or tests bleed into
    each other:

    * `app.db.engine` — bound at import time to an empty scratch file, so every
      client overrides `get_session` with the test's own Session.
    * the login rate limiter (§7) — module-level in `app.routers.auth` and
      deliberately per-process, so one test's failed logins would 429 the next.
      Cleared on both sides of every test.

    `target` defaults to the real app; permission tests pass their probe app.
    """
    from app.db import get_session
    from app.routers.auth import _ip_limiter, _username_limiter

    _username_limiter.clear()
    _ip_limiter.clear()

    overridden: list[FastAPI] = []
    clients: list[TestClient] = []

    def factory(target: FastAPI | None = None, *, ip: str = DEFAULT_CLIENT_IP) -> TestClient:
        from app.main import app as real_app

        resolved = real_app if target is None else target
        if resolved not in overridden:
            resolved.dependency_overrides[get_session] = lambda: session
            overridden.append(resolved)
        client = TestClient(resolved, client=(ip, 51000))
        clients.append(client)
        return client

    try:
        yield factory
    finally:
        for client in clients:
            client.close()
        for target in overridden:
            target.dependency_overrides.clear()
        _username_limiter.clear()
        _ip_limiter.clear()


@pytest.fixture
def client(api_client_factory: Callable[..., TestClient]) -> TestClient:
    """A TestClient for the real app (`app.main.app`)."""
    return api_client_factory()
