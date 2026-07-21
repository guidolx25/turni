"""Email transport (spec §10 Channel 2, §11 `RESEND_API_KEY`).

This module knows how to put a message on the wire and nothing else: what to say
is `app.email_templates`, whom to say it to is `app.notifications`. Splitting it
that way is what lets the whole test suite run with zero network I/O — the
transport is a swappable seam, not a hardcoded `httpx.post` inside `notify()`.

Two implementations of the `EmailTransport` protocol:

* `ResendTransport` — the real §11 Resend API call, selected when
  `RESEND_API_KEY` is set.
* `NullTransport` — selected when it is not. It *collects* what would have been
  sent rather than discarding it, so dev can inspect the outbox and tests can
  assert on content without mocking `httpx`.

**Failures never propagate.** `send_email` catches transport errors and logs
them. §10 makes a notification a side effect of a domain event: a Resend outage
must not roll back a published schedule or an applied swap, so nothing here may
raise into the caller's transaction.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"


@dataclass(frozen=True)
class EmailMessage:
    """One rendered message. `text` is the body of record; `html` is a minimal
    presentational wrapper — every client that cannot render it still gets the
    full content (§10 says "templated", not "designed")."""

    to: str
    subject: str
    text: str
    html: str


class EmailTransport(Protocol):
    """The seam. Anything that can accept an `EmailMessage` is a transport."""

    def send(self, message: EmailMessage) -> None:
        """Deliver `message`. May raise; `send_email` is what swallows."""


class NullTransport:
    """The no-network transport: records instead of sending.

    Used whenever `RESEND_API_KEY` is unset — i.e. dev and the entire test
    suite. Keeping the messages (rather than dropping them) is deliberate: it
    makes "what would have been sent" an assertable fact, which is the only way
    to test Channel 2's content without standing up a fake HTTP server.

    Thread-safe because APScheduler jobs (§11) fire on a background thread while
    requests are served on others, and both go through `notify()`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        with self._lock:
            self._sent.append(message)
        logger.info(
            "email suppressed (no RESEND_API_KEY): to=%s subject=%s", message.to, message.subject
        )

    @property
    def sent(self) -> list[EmailMessage]:
        """A snapshot of everything collected so far."""
        with self._lock:
            return list(self._sent)

    def clear(self) -> None:
        with self._lock:
            self._sent.clear()


class ResendTransport:
    """§11: the Resend API. One POST per message, bounded by a timeout.

    Synchronous on purpose. `notify()` is called from inside the caller's
    transaction, and an async hop there would mean either a task queue (not in
    v1) or a session held across an await. The timeout is what keeps a slow
    Resend from becoming a slow request.
    """

    def __init__(self, api_key: str, sender: str, timeout: float) -> None:
        self._api_key = api_key
        self._sender = sender
        self._timeout = timeout

    def send(self, message: EmailMessage) -> None:
        response = httpx.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "from": self._sender,
                "to": [message.to],
                "subject": message.subject,
                "text": message.text,
                "html": message.html,
            },
            timeout=self._timeout,
        )
        response.raise_for_status()


def _build_transport() -> EmailTransport:
    """Select the transport from config (§11). No key -> no network."""
    if not settings.resend_api_key:
        return NullTransport()
    return ResendTransport(
        settings.resend_api_key, settings.resend_from, settings.resend_timeout_seconds
    )


# Built lazily and cached, so importing this module never reads config at import
# time and a test can pin the transport before the first send.
_transport: EmailTransport | None = None


def get_transport() -> EmailTransport:
    """The active transport, built from config on first use."""
    global _transport
    if _transport is None:
        _transport = _build_transport()
    return _transport


def set_transport(transport: EmailTransport | None) -> None:
    """Swap the transport (tests, and dev tooling). `None` resets to config."""
    global _transport
    _transport = transport


def send_email(to: str, subject: str, text: str, html: str) -> bool:
    """Hand one message to the active transport. Returns whether it went out.

    Never raises. §10 email is a *side effect* of a domain event, so a transport
    failure is logged and dropped: the published schedule or applied swap that
    triggered it must still commit. `httpx.HTTPError` covers connect/read
    timeouts and `raise_for_status`; the second clause catches a transport that
    fails some other way (bad config, an OS-level socket error) without ever
    widening to a bare `except`.
    """
    message = EmailMessage(to=to, subject=subject, text=text, html=html)
    try:
        get_transport().send(message)
    except httpx.HTTPError:
        logger.exception("email send failed (transport error): to=%s subject=%s", to, subject)
        return False
    except OSError:
        logger.exception("email send failed (network error): to=%s subject=%s", to, subject)
        return False
    return True
