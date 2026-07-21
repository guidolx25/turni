"""Alembic environment for the Turni SQLite database.

Two settings matter beyond the stock template:

* `render_as_batch=True` — SQLite cannot ALTER a column or drop a constraint, so
  alembic must rebuild tables via batch mode. Combined with the named-constraint
  convention on `Base.metadata`, this keeps future migrations (and downgrades)
  workable.
* the URL comes from app settings, not alembic.ini, so migrations always hit the
  same database the app does (§11: config via env).
"""

from logging.config import fileConfig
from typing import Any

from sqlalchemy import engine_from_config, pool

from alembic import context

# `models` is imported for its side effect: every table registers on the shared
# MetaData, which is what autogenerate diffs against.
from app import models  # noqa: F401
from app.config import settings
from app.db import Base, UtcDateTime

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    # `disable_existing_loggers=False` is load-bearing, not a preference.
    # `fileConfig` defaults to True, which sets `disabled = True` on every logger
    # that already exists — including all of `app.*` — for the REST OF THE
    # PROCESS. Alembic run as a standalone command that is harmless (it exits),
    # but running migrations in-process (a deployment that upgrades at startup,
    # a test that migrates) would silently mute the application's own logging,
    # and §11's ops surface IS the log: the failure mode is a running server that
    # reports nothing.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def render_item(type_: str, obj: Any, autogen_context: Any) -> str | bool:
    """Keep migrations free of imports from `app`.

    A migration is a frozen snapshot of DDL; if it imported `app.db.UtcDateTime`
    it would break the day that class is moved or renamed. `UtcDateTime` is only
    Python-side normalisation over `DateTime(timezone=True)`, so the DDL-level
    equivalent renders instead.
    """
    if type_ == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    """Emit SQL without a DBAPI connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            render_item=render_item,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
