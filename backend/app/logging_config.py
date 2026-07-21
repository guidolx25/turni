"""Structured JSON logging (spec §11 "structured logs").

Discharges the Phase 0 carry-forward: `app.main` shipped a `logging.basicConfig`
placeholder whose comment deferred real structured logging to §11, because the
messages that matter most are the ones that break a line-oriented format. §8
requires solver runs to be logged "with duration + objective values", and those
messages carry braces, quotes and worker names; §2.3 escalations carry a JSON
unsat core. Concatenated into a `%`-format line, any of those can produce output
that a log shipper parses as a different record — or as none.

So the message and every structured field go through `json.dumps`, which is the
only escaping in the module: one JSON object per line, values quoted by the
encoder rather than by hand.

Dependency-light on purpose (§11 keeps the deployment a single container): a
`logging.Formatter` subclass and the stdlib `json`, no third-party logging stack.

**uvicorn.** Uvicorn installs its own handlers on `uvicorn`, `uvicorn.error` and
`uvicorn.access` and sets `propagate = False`, so a root-level formatter never
sees a request log — which is exactly what the carry-forward noted was missing.
`configure_logging` therefore takes those loggers over explicitly: handlers
dropped, propagation restored, so access logs land in the same JSON stream as
everything else.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

# `logging.LogRecord`'s own attributes. Anything else on a record was put there
# by a caller's `extra=` and is emitted as a structured field.
_RESERVED: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

# The loggers uvicorn configures for itself (see the module docstring).
_UVICORN_LOGGERS: tuple[str, ...] = ("uvicorn", "uvicorn.error", "uvicorn.access")


class JsonFormatter(logging.Formatter):
    """One JSON object per record, on one line.

    Timestamps are UTC ISO-8601 (project convention: store/emit UTC, convert to
    Europe/Rome only at a user-facing edge — a log line is not one).

    A value that json cannot encode is `repr`'d rather than dropped: a log line is
    diagnostics, and losing the field would hide the very thing being diagnosed.
    Encoding never raises, so a bad `extra=` cannot take down the caller.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            # `getMessage` applies the %-args; the result is a VALUE here, quoted
            # and escaped by the encoder, so braces and quotes inside it (§8's
            # objective breakdowns, §2.3's conflict data) cannot break the line.
            "message": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=repr, ensure_ascii=False)


def configure_logging(level: str = "INFO", *, json_format: bool = True) -> None:
    """Install the §11 log configuration on the root logger.

    Idempotent: the root's handlers are replaced, not appended to, so calling it
    twice (import plus a test) does not double every line.

    `json_format=False` falls back to a plain human line — for a developer at a
    terminal, where a JSON object per line is worse than useless. Never disables
    existing loggers: see `alembic/env.py`, where doing so silently killed every
    `app.*` logger for the rest of the process.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter()
        if json_format
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Take uvicorn's loggers over so request/access logs join the same stream
    # (§11). Uvicorn owns their configuration, so this must run after uvicorn has
    # configured them — importing the app happens after that, which is why this is
    # called at `app.main` import.
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
