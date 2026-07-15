"""Database plumbing: declarative Base, naming convention, UTC datetime type.

Spec §6 targets SQLite. Two SQLite realities shape this module:

1. No native ENUM and no real ALTER — every enum column is a VARCHAR + CHECK
   constraint, and migrations run in alembic batch mode (table copy). Batch mode
   can only reproduce constraints it can *name*, so MetaData carries an explicit
   naming convention.
2. No timezone-aware storage. Per project convention the DB holds UTC and
   conversion happens at the edges, so `UtcDateTime` enforces that invariant in
   the type layer rather than trusting every call site.
"""

from __future__ import annotations

import datetime as dt
import enum
from collections.abc import Generator
from typing import Any

from sqlalchemy import DateTime, Enum, MetaData, create_engine, event
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.config import settings

# Deterministic constraint names. Without these, SQLite CHECK/UNIQUE constraints
# come out unnamed and alembic batch migrations cannot drop or recreate them.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata_obj = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base carrying the shared, named-constraint MetaData."""

    metadata = metadata_obj


class UtcDateTime(TypeDecorator[dt.datetime]):
    """A datetime that is always tz-aware UTC in Python and UTC in the DB.

    SQLite drops tzinfo, so a plain `DateTime(timezone=True)` silently hands back
    naive datetimes and any later Europe/Rome conversion (§3 window deadlines)
    would be wrong by an hour or two depending on DST. Normalising here means the
    ambiguity cannot reach the domain code.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect: Dialect) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected: pass a tz-aware value (UTC is stored)")
        return value.astimezone(dt.UTC)

    def process_result_value(
        self, value: dt.datetime | None, dialect: Dialect
    ) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value.astimezone(dt.UTC)


def utcnow() -> dt.datetime:
    """Current instant as tz-aware UTC (the only accepted `created_at` source)."""
    return dt.datetime.now(dt.UTC)


def enum_column(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Build the enum type for a §6 ENUM column.

    `native_enum=False` + `create_constraint=True` is what turns an enum into a
    VARCHAR + named CHECK on SQLite. `values_callable` stores the member *values*
    (the lowercase spec strings such as 'am', 'bagnino'), not the member names —
    SQLAlchemy's default is the name, which would put the wrong text in the DB.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )


engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    """SQLite ignores FK constraints unless asked per connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_session() -> Generator[Session, Any, None]:
    """Session-per-request dependency."""
    with SessionLocal() as session:
        yield session
