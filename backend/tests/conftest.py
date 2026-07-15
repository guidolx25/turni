"""Shared fixtures for the schema suite (spec §6).

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
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Set before `app.config` is imported anywhere: protects the dev database.
_SCRATCH = Path(tempfile.mkdtemp(prefix="turni-test-session-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_SCRATCH / 'session.db'}"

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import Connection, Engine, create_engine, event, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from alembic import command  # noqa: E402


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
