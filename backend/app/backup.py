"""Nightly SQLite backup (spec §11: "nightly `sqlite3 .backup` to the volume, keep 14").

Uses SQLite's **online backup API** (`sqlite3.Connection.backup`), not a file
copy. §11 says `.backup` for a reason: the app is a single container running
FastAPI *and* APScheduler against one database file, so the backup necessarily
runs while requests can be writing. `shutil.copyfile` reads pages without holding
a read transaction, so it can capture a file mid-write and produce an image that
is corrupt or silently missing the tail of a committed transaction — and a backup
that is only discovered to be bad when it is restored is worse than none. The
backup API copies pages under SQLite's own locking and restarts if a write lands
mid-copy, so the destination is always a consistent snapshot of some committed
state.

Failure policy: **loud but not fatal**. §11's ops surface is the log; an
unwritable backup directory must be shouted about (an operator who does not know
their backups stopped has no backups), but raising out of a scheduled job would
let APScheduler retire the job entirely, so tomorrow's attempt — which might
succeed, the volume having been remounted — would never happen. So every failure
is logged with a traceback and swallowed, and the caller learns via the return
value.
"""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import settings

logger = logging.getLogger(__name__)

# `turni-20260721T013000Z.db` — UTC, so the names sort chronologically and do not
# collide or reorder across a DST change (project convention: UTC at rest,
# Europe/Rome only at a user-facing edge; a filename is not one).
BACKUP_PREFIX = "turni-"
BACKUP_SUFFIX = ".db"
_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"


def source_database_path() -> Path | None:
    """The SQLite file behind `DATABASE_URL`, or None if the URL is not a file.

    §11 fixes SQLite for v1, but an in-memory URL (some tests) or a future
    non-SQLite backend has no file to snapshot, and this returns None so the job
    skips rather than inventing a path.
    """
    url = make_url(settings.database_url)
    if not url.drivername.startswith("sqlite") or not url.database:
        return None
    if url.database == ":memory:":
        return None
    return Path(url.database)


def backup_filename(now: dt.datetime) -> str:
    """The name of the snapshot taken at `now` (UTC)."""
    return f"{BACKUP_PREFIX}{now.astimezone(dt.UTC).strftime(_TIMESTAMP_FORMAT)}{BACKUP_SUFFIX}"


def list_backups(directory: Path) -> list[Path]:
    """Existing snapshots, newest first.

    Ordered by FILENAME, which is the UTC timestamp — not by mtime, which a
    volume restore or an `rsync` can rewrite, and which would then prune the
    wrong files.
    """
    if not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}") if p.is_file()),
        key=lambda p: p.name,
        reverse=True,
    )


def prune_backups(directory: Path, keep: int) -> list[Path]:
    """Delete all but the `keep` newest snapshots; returns what was deleted (§11).

    A file that vanished between listing and unlinking is not an error — another
    run or an operator got there first, and the post-condition ("at most `keep`
    remain") holds either way.
    """
    removed: list[Path] = []
    for stale in list_backups(directory)[max(keep, 0) :]:
        try:
            stale.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            logger.exception("could not prune backup", extra={"path": str(stale)})
            continue
        removed.append(stale)
    return removed


def create_backup(now: dt.datetime, *, directory: Path | None = None) -> Path | None:
    """Take one online-API snapshot into `directory` (default `BACKUP_DIR`).

    Returns the snapshot's path, or None if it could not be taken (no SQLite file
    behind the URL, unwritable directory, SQLite error). Never raises: see the
    module docstring on why a scheduled job must survive its own failure.
    """
    target_dir = directory if directory is not None else settings.backup_dir
    source = source_database_path()
    if source is None:
        logger.warning("nightly backup skipped: DATABASE_URL names no SQLite file")
        return None
    if not source.exists():
        logger.error(
            "nightly backup skipped: database file is missing", extra={"path": str(source)}
        )
        return None

    destination = target_dir / backup_filename(now)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        # `contextlib.closing`, NOT `with sqlite3.connect(...)`: a sqlite3
        # connection's own context manager is a TRANSACTION scope that commits or
        # rolls back and leaves the connection open. In a long-lived process that
        # leaks a file handle (and a lock on the volume) every night.
        with (
            closing(sqlite3.connect(source)) as src,
            closing(sqlite3.connect(destination)) as dst,
        ):
            src.backup(dst)  # §11: the online backup API, never a file copy
    except (OSError, sqlite3.Error):
        # Loud (with traceback) but not fatal — the scheduler must live to try
        # again tomorrow.
        logger.exception("nightly backup FAILED", extra={"destination": str(destination)})
        _discard_partial(destination)
        return None

    logger.info("nightly backup written", extra={"destination": str(destination)})
    return destination


def _discard_partial(destination: Path) -> None:
    """Remove a snapshot that failed halfway.

    A truncated file would otherwise sit in the directory looking exactly like a
    good backup, count against the retention window, and push a real one out.
    """
    try:
        destination.unlink(missing_ok=True)
    except OSError:
        logger.exception("could not remove partial backup", extra={"path": str(destination)})
