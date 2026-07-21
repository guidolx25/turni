"""§10 Channel 2 — the email transport, templates and the `notify()` fan-out.

Three separable claims, tested separately:

1. `app.email` selects a no-network transport when `RESEND_API_KEY` is unset, and
   a transport failure never escapes `send_email`.
2. `app.email_templates` has both languages for every §10 event, and renders the
   *user's* language.
3. `notify()` reaches both channels for an opted-in user and only Channel 1 for
   an opted-out one — without any call site knowing a second channel exists.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import email_templates
from app.email import EmailMessage, NullTransport, ResendTransport, send_email, set_transport
from app.enums import Language
from app.models import Notification
from app.notifications import (
    ALL_EVENTS,
    EVENT_SCHEDULE_PUBLISHED,
    EVENT_SWAP_REQUESTED,
    notify,
)
from tests.factories import create_user

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase5

WEEK_PAYLOAD = {"week": "2026-07-13"}


class ExplodingTransport:
    """A transport that always fails, the way a Resend outage would."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def send(self, message: EmailMessage) -> None:
        raise self._error


# --- transport selection & failure containment ------------------------------


def test_null_transport_collects_instead_of_sending(email_outbox: NullTransport) -> None:
    """The dev/test default records what WOULD have gone out (no network)."""
    assert send_email("a@example.com", "subject", "text", "<p>text</p>") is True
    assert [m.to for m in email_outbox.sent] == ["a@example.com"]
    assert email_outbox.sent[0].subject == "subject"


def test_transport_is_resend_only_when_the_key_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """§11: no RESEND_API_KEY means no network transport is ever constructed."""
    from app.config import settings
    from app.email import _build_transport

    monkeypatch.setattr(settings, "resend_api_key", "")
    assert isinstance(_build_transport(), NullTransport)
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    assert isinstance(_build_transport(), ResendTransport)


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectTimeout("timeout"), httpx.HTTPError("boom"), OSError("socket gone")],
)
def test_send_email_swallows_transport_failures(error: Exception) -> None:
    """§10: email is a side effect of a domain event. A dead Resend must not be
    able to raise into — and therefore roll back — the caller's transaction."""
    set_transport(ExplodingTransport(error))
    assert send_email("a@example.com", "s", "t", "<p>t</p>") is False


def test_notify_survives_a_dead_transport(session: DbSession) -> None:
    """The in-app row still lands when the email channel is down."""
    user = create_user(session, "pasha", email="pasha@example.com")
    set_transport(ExplodingTransport(httpx.HTTPError("boom")))

    notify(session, user, EVENT_SCHEDULE_PUBLISHED, WEEK_PAYLOAD)
    session.commit()

    rows = session.scalars(select(Notification).where(Notification.user_id == user.id)).all()
    assert len(rows) == 1


# --- template registry ------------------------------------------------------


def test_every_spec_event_has_both_languages() -> None:
    """§10's event list, IT and EN, with no gaps in either direction."""
    assert email_templates.SUPPORTED_EVENTS == ALL_EVENTS
    for event in ALL_EVENTS:
        for language in Language:
            rendered = email_templates.render(event, language, WEEK_PAYLOAD)
            assert rendered is not None, f"{event}/{language.value}"
            assert rendered.subject.strip()
            assert rendered.text.strip()
            assert rendered.html.strip()


def test_language_parity_guard_rejects_a_half_translated_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard is the thing that makes a missing translation unshippable."""
    broken: dict[str, dict[Language, Any]] = {
        "schedule_published": {Language.IT: lambda p: ("solo italiano", [])}
    }
    monkeypatch.setattr(email_templates, "_TEMPLATES", broken)
    with pytest.raises(RuntimeError, match="missing language"):
        email_templates._assert_language_parity()


def test_weekdays_are_localized_per_language() -> None:
    """No Italian leaking into an English body, or vice versa."""
    payload = {"week": "2026-07-13", "proposed_free_day": "fri"}
    italian = email_templates.render("sacrifice_proposed", Language.IT, payload)
    english = email_templates.render("sacrifice_proposed", Language.EN, payload)
    assert italian is not None and english is not None
    assert "venerdì" in italian.text
    assert "Friday" in english.text
    assert "venerdì" not in english.text
    assert "Friday" not in italian.text


def test_dates_are_localized_per_language() -> None:
    assert email_templates.date_label("2026-07-13", Language.IT) == "13/07/2026"
    assert email_templates.date_label("2026-07-13", Language.EN) == "13 July 2026"


def test_templates_never_raise_on_a_missing_key() -> None:
    """A payload gap is a formatting problem, not a lost notification."""
    for event in ALL_EVENTS:
        for language in Language:
            assert email_templates.render(event, language, None) is not None


def test_html_escapes_payload_values() -> None:
    """`display_name` is user-supplied and reaches the HTML body."""
    payload = {"week": "2026-07-13", "display_name": "<script>x</script>", "day": "sat"}
    rendered = email_templates.render("weekend_hard_escalated", Language.EN, payload)
    assert rendered is not None
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html


def test_unknown_event_has_no_template() -> None:
    """§6 makes `event_type` free text; an untemplated event is in-app only."""
    assert email_templates.render("not_a_spec_event", Language.IT, {}) is None


# --- notify() fan-out -------------------------------------------------------


def test_notify_sends_both_channels_for_an_opted_in_user(
    session: DbSession, email_outbox: NullTransport
) -> None:
    """The Phase 5 gate: every event produces both channels for an opted-in user."""
    user = create_user(session, "pasha", email="pasha@example.com")

    notify(session, user, EVENT_SCHEDULE_PUBLISHED, WEEK_PAYLOAD)
    session.commit()

    assert session.scalars(select(Notification).where(Notification.user_id == user.id)).all()
    assert [m.to for m in email_outbox.sent] == ["pasha@example.com"]


def test_notify_respects_the_per_user_opt_out(
    session: DbSession, email_outbox: NullTransport
) -> None:
    """§10: per-user opt-out. Channel 1 still fires — the bell is not optional."""
    user = create_user(session, "pasha", email="pasha@example.com")
    user.email_notifications = False
    session.commit()

    notify(session, user, EVENT_SCHEDULE_PUBLISHED, WEEK_PAYLOAD)
    session.commit()

    assert session.scalars(select(Notification).where(Notification.user_id == user.id)).all()
    assert email_outbox.sent == []


def test_notify_skips_email_without_an_address(
    session: DbSession, email_outbox: NullTransport
) -> None:
    """§6 makes `users.email` nullable; there is simply nowhere to send."""
    user = create_user(session, "pasha", email=None)
    notify(session, user, EVENT_SCHEDULE_PUBLISHED, WEEK_PAYLOAD)
    session.commit()
    assert email_outbox.sent == []


def test_email_follows_the_users_language_not_a_global_setting(
    session: DbSession, email_outbox: NullTransport
) -> None:
    """§9/§10: email language follows `users.language`, per recipient."""
    italian = create_user(session, "pasha", email="it@example.com", language=Language.IT)
    english = create_user(session, "amir", email="en@example.com", language=Language.EN)

    payload = {
        "week": "2026-07-13",
        "from_assignment": {"id": 1, "day": "mon", "slot": "am", "role": "bagnino"},
        "to_assignment": {"id": 2, "day": "tue", "slot": "pm", "role": "bagnino"},
    }
    notify(session, italian, EVENT_SWAP_REQUESTED, payload)
    notify(session, english, EVENT_SWAP_REQUESTED, payload)
    session.commit()

    by_recipient = {m.to: m for m in email_outbox.sent}
    assert "scambio" in by_recipient["it@example.com"].subject.lower()
    assert "swap" in by_recipient["en@example.com"].subject.lower()
    assert "lunedì" in by_recipient["it@example.com"].text
    assert "Monday" in by_recipient["en@example.com"].text
