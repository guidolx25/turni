"""Deployment & ops (spec §11) — backups, structured logs, health.

§11 asks for four things this suite pins: a nightly `sqlite3 .backup` keeping 14,
structured logs, a health endpoint, and config via env. Two of them are Phase 0
carry-forwards being discharged here: the `logging.basicConfig` placeholder in
`app.main`, and `alembic/env.py`'s `fileConfig` call, which disabled every
`app.*` logger for the rest of the process (the test suite masks it with an
autouse fixture; the app-side hazard was still real).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import shutil
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import backup as backup_module
from app.backup import backup_filename, create_backup, list_backups, prune_backups
from app.config import settings
from app.jobs import run_nightly_maintenance
from app.logging_config import JsonFormatter, configure_logging
from app.models import AuditLog
from app.models import Session as SessionRow
from app.notifications import ALL_EVENTS, SPEC_EVENT_COUNT, SPEC_EVENTS
from app.scheduler import NIGHTLY_MAINTENANCE_JOB_ID, build_scheduler
from tests.factories import create_worker

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase6

_NOW = dt.datetime(2026, 7, 21, 1, 30, tzinfo=dt.UTC)


# --- §11 nightly SQLite backup ----------------------------------------------


def test_the_backup_is_a_usable_snapshot(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11: "nightly `sqlite3 .backup` to the volume".

    The snapshot must be a real, openable database with the source's rows — not a
    byte range that happens to exist. Read back through sqlite3 rather than
    compared as bytes: SQLite is free to lay pages out differently, and it is the
    CONTENT that has to survive.
    """
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    with sqlite3.connect(db_path) as conn:
        conn.execute("INSERT INTO weeks (monday_date, status) VALUES ('2026-07-13', 'open')")
        conn.commit()

    snapshot = create_backup(_NOW, directory=tmp_path)
    assert snapshot is not None and snapshot.exists()
    assert snapshot.name == backup_filename(_NOW)

    with sqlite3.connect(snapshot) as restored:
        rows = restored.execute("SELECT monday_date FROM weeks").fetchall()
    assert rows == [("2026-07-13",)]


def test_the_backup_uses_the_online_api_not_a_file_copy(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§11 says `.backup` for a reason: the app writes to this file while the job
    runs, and a plain copy can capture it mid-write. Pinned by observing that the
    connection's `backup` method is what produces the snapshot — a future
    "optimisation" to `shutil.copyfile` fails here rather than in production, six
    months later, during a restore."""
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    calls: list[str] = []
    real_connect = sqlite3.connect

    class _SpyConnection:
        """A pass-through around a real connection that records `backup` calls.

        `sqlite3.Connection` is an immutable C type, so its method cannot be
        patched; wrapping the factory is the way to observe which API the module
        actually reaches for.
        """

        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn

        def backup(self, target: object, **kwargs: object) -> None:
            calls.append("backup")
            unwrapped = target._conn if isinstance(target, _SpyConnection) else target
            self._conn.backup(unwrapped, **kwargs)  # type: ignore[arg-type]

        def close(self) -> None:
            self._conn.close()

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: _SpyConnection(real_connect(*a, **k)))
    monkeypatch.setattr(
        shutil, "copyfile", lambda *a, **k: pytest.fail("§11 forbids a file copy here")
    )

    assert create_backup(_NOW, directory=tmp_path) is not None
    assert calls == ["backup"], "the snapshot must come from the online backup API"


def test_pruning_keeps_the_fourteen_newest(tmp_path: Path) -> None:
    """§11: "keep 14". Ordering is by the UTC timestamp in the FILENAME, not by
    mtime — a volume restore or an rsync rewrites mtimes and would prune the
    wrong files."""
    for day in range(1, 21):
        (tmp_path / f"turni-202607{day:02d}T013000Z.db").write_text("x")
    (tmp_path / "unrelated.txt").write_text("keep me")

    removed = prune_backups(tmp_path, 14)
    remaining = [p.name for p in list_backups(tmp_path)]
    assert len(remaining) == 14
    assert remaining[0] == "turni-20260720T013000Z.db", "newest first"
    assert remaining[-1] == "turni-20260707T013000Z.db"
    assert len(removed) == 6
    assert (tmp_path / "unrelated.txt").exists(), "only our own snapshots are pruned"


def test_an_unwritable_backup_directory_is_loud_but_not_fatal(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """§11 ops surface is the log. An operator who does not know their backups
    stopped has no backups — so the failure is logged with a traceback. It must
    NOT raise: an exception out of a scheduled job lets APScheduler retire it, so
    tomorrow's attempt (with the volume remounted) would never happen.
    """
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    blocked = tmp_path / "blocked"
    blocked.write_text("this is a file, not a directory")

    with caplog.at_level(logging.ERROR, logger="app.backup"):
        assert create_backup(_NOW, directory=blocked) is None
    assert any("FAILED" in record.message for record in caplog.records)


def test_a_missing_database_file_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'nope.db'}")
    with caplog.at_level(logging.ERROR, logger="app.backup"):
        assert create_backup(_NOW, directory=tmp_path) is None
    assert caplog.records


def test_the_nightly_job_audits_with_a_null_actor(
    session: DbSession, db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6: "actor_id NULL means a system action (cron solve, 48 h swap expiry,
    **nightly backup**) ... there is deliberately no system user row."

    The audit row is what lets an operator establish afterwards that backups
    actually ran — and notice, from a null `backup` field, when one did not.
    """
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "backup_dir", tmp_path)

    snapshot = run_nightly_maintenance(session, _NOW)
    assert snapshot is not None

    entry = session.scalars(
        select(AuditLog).where(AuditLog.action == "backup").order_by(AuditLog.id.desc())
    ).first()
    assert entry is not None
    assert entry.actor_id is None, "§6: a scheduled job has no human actor"
    assert entry.entity == "database"
    assert entry.payload is not None and entry.payload["backup"] == str(snapshot)


def test_the_nightly_job_purges_expired_sessions(
    session: DbSession, db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§6 `sessions`: "expired rows are purged by the nightly job (§11)". Expiry
    is already enforced on read, so this is housekeeping — but it is housekeeping
    the spec assigns to this job, and nothing was doing it."""
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr(settings, "backup_dir", tmp_path)
    user = create_worker(session)
    session.add(
        SessionRow(id="stale-token", user_id=user.id, expires_at=_NOW - dt.timedelta(days=1))
    )
    session.add(
        SessionRow(id="live-token", user_id=user.id, expires_at=_NOW + dt.timedelta(days=1))
    )
    session.commit()

    run_nightly_maintenance(session, _NOW)

    session.expire_all()
    remaining = {s.id for s in session.scalars(select(SessionRow)).all()}
    assert remaining == {"live-token"}


def test_the_nightly_job_is_scheduled() -> None:
    """§11: nightly. Registered on the same Europe/Rome scheduler as §3's crons,
    so it follows DST like everything else."""
    scheduler = build_scheduler()
    job = scheduler.get_job(NIGHTLY_MAINTENANCE_JOB_ID)
    assert job is not None
    assert str(job.trigger.timezone) == settings.tz
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == str(settings.backup_hour)
    assert fields["minute"] == str(settings.backup_minute)


def test_backup_config_is_env_driven() -> None:
    """§11: "Config via env". The retention the spec names is the default."""
    assert settings.backup_keep == 14
    assert isinstance(settings.backup_dir, Path)


def test_a_non_sqlite_url_skips_rather_than_guessing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "database_url", "postgresql://user@host/db")
    assert backup_module.source_database_path() is None
    assert create_backup(_NOW, directory=tmp_path) is None


# --- §11 structured logs -----------------------------------------------------


def test_log_records_are_one_json_object_per_line() -> None:
    """§11: "structured logs"."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.solver.model",
        level=logging.INFO,
        pathname=__file__,
        lineno=42,
        msg="solver OPTIMAL in %.3fs",
        args=(0.011,),
        exc_info=None,
    )
    line = formatter.format(record)
    assert "\n" not in line
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.solver.model"
    assert payload["message"] == "solver OPTIMAL in 0.011s"
    assert payload["line"] == 42
    dt.datetime.fromisoformat(payload["ts"])  # parses, and is UTC-aware


def test_a_message_full_of_quotes_and_braces_stays_one_record() -> None:
    """The reason §11's logs could not just be a format string.

    §8 requires solver runs logged "with duration + objective values" and §2.3
    escalations carry the unsat core as JSON; both put braces and quotes inside
    the message. Concatenated into a line-oriented format they can produce output
    a collector reads as a different record — or as none. Here the message is a
    VALUE, escaped by the encoder.
    """
    formatter = JsonFormatter()
    nasty = 'conflict={"worker_id": 3, "day": "fri"} said "no"\nsecond line'
    record = logging.LogRecord(
        name="app.sacrifice_service",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg=nasty,
        args=None,
        exc_info=None,
    )
    line = formatter.format(record)
    assert line.count("\n") == 0, "an embedded newline must not split the record"
    assert json.loads(line)["message"] == nasty


def test_extra_fields_and_exceptions_are_structured() -> None:
    """`extra=` becomes real fields (that is the point of structured logs), and a
    traceback travels inside the object rather than as a dozen loose lines."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.backup",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="nightly backup FAILED",
        args=None,
        exc_info=None,
    )
    record.destination = "/data/backups/turni.db"
    try:
        raise OSError("read-only file system")
    except OSError as exc:
        record.exc_info = (type(exc), exc, exc.__traceback__)
    payload = json.loads(formatter.format(record))
    assert payload["destination"] == "/data/backups/turni.db"
    assert "read-only file system" in payload["exception"]


def test_an_unencodable_value_is_repred_not_dropped() -> None:
    """A log line is diagnostics; losing the field would hide the thing being
    diagnosed, and raising would let a bad `extra=` take down its caller."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="x",
        args=None,
        exc_info=None,
    )
    record.weird = object()
    assert "object object at" in json.loads(formatter.format(record))["weird"]


def test_configure_logging_covers_uvicorns_own_loggers() -> None:
    """Uvicorn installs its own handlers and sets `propagate = False`, so request
    logs would never reach a root formatter — which is exactly what the Phase 0
    carry-forward noted was uncovered. `configure_logging` takes them over."""
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        hijacked = logging.getLogger(name)
        hijacked.addHandler(logging.NullHandler())
        hijacked.propagate = False

    configure_logging("INFO", json_format=True)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        covered = logging.getLogger(name)
        assert covered.handlers == []
        assert covered.propagate is True
    root_handlers = logging.getLogger().handlers
    assert len(root_handlers) == 1
    assert isinstance(root_handlers[0].formatter, JsonFormatter)


def test_configure_logging_is_idempotent() -> None:
    """Called twice (import plus a test), it must not double every line."""
    configure_logging("INFO")
    configure_logging("INFO")
    assert len(logging.getLogger().handlers) == 1


def test_configure_logging_never_disables_existing_loggers() -> None:
    """The failure mode `alembic/env.py` used to cause, asserted directly."""
    app_logger = logging.getLogger("app.some.module")
    configure_logging("INFO")
    assert app_logger.disabled is False


def test_alembic_env_does_not_silence_the_application(tmp_path: Path) -> None:
    """The Phase 0 carry-forward, fixed at the source.

    `logging.config.fileConfig` defaults to `disable_existing_loggers=True`, which
    sets `disabled = True` on every logger that already exists — including all of
    `app.*` — for the rest of the PROCESS. Run in-process (a deploy that migrates
    at startup), that leaves a server whose §11 ops surface reports nothing.

    The suite's autouse fixture un-disables `app.*` loggers, so this test asserts
    on a logger OUTSIDE that namespace: it would still be disabled if `env.py`
    regressed.
    """
    from tests.conftest import run_upgrade, sqlite_url

    canary = logging.getLogger("canary.not.app")
    assert canary.disabled is False
    run_upgrade(sqlite_url(tmp_path / "migrated.db"))
    assert canary.disabled is False, "alembic must pass disable_existing_loggers=False"


# --- §11 health --------------------------------------------------------------


def test_healthz_is_unauthenticated_and_checks_the_database(client: TestClient) -> None:
    """§11: a probe must not need a session, and must fail when the volume the
    database lives on is not there — a container serving 200s while every real
    request 500s is what a constant body would hide."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_healthz_reports_503_when_the_database_is_unreachable(
    client: TestClient, session: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("no such volume"))

    monkeypatch.setattr(session, "execute", boom)
    resp = client.get("/healthz")
    assert resp.status_code == 503
    assert resp.json()["detail"] == "database_unavailable"


# --- §10's closed event list -------------------------------------------------


def test_the_event_names_are_pinned_to_the_spec() -> None:
    """§10 enumerates exactly ten events.

    `ALL_EVENTS` and `email_templates.SUPPORTED_EVENTS` are both derived from
    code, so checking them against each other only proves they AGREE: deleting an
    event from both would leave a self-consistent system that no longer implements
    §10. `SPEC_EVENTS` is a third, independent transcription of the spec's literal
    names, and this test is the fourth — so a deletion has to be made in three
    places and past a red test before it can ship.
    """
    assert len(SPEC_EVENTS) == SPEC_EVENT_COUNT == 10
    assert set(SPEC_EVENTS) == {
        "schedule_published",
        "swap_requested",
        "swap_accepted",
        "swap_rejected",
        "sacrifice_proposed",
        "sacrifice_resolved",
        "sacrifice_escalated",
        "weekend_hard_escalated",
        "window_closing_24h",
        "admin_override",
    }
    assert frozenset(SPEC_EVENTS) == ALL_EVENTS
