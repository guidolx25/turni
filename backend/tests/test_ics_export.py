"""The per-user calendar feed (spec §7 `GET /export/ics`, §6 v1.7, §3.3).

The feed is the one endpoint outside the session cookie: calendar apps poll it
headless, so the credential is `users.ics_token`. Three properties matter and
each has a test here — it shows only PUBLISHED weeks (§3.3), only the token
owner's own shifts, and it is not an oracle (every failure is one 404).

Times are read from the deploy-time settings rather than hardcoded, so the
DST assertions stay true if the provisional hours are ever retuned (§11).
"""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.enums import WeekStatus
from app.models import User
from app.publish_service import publish_week
from app.scheduling import get_or_create_week
from app.schemas import UserOut
from app.solve_service import run_solve
from tests.factories import PASSWORD, create_full_roster

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase4

ROME = ZoneInfo("Europe/Rome")

# A summer week (Rome is UTC+2, CEST) and a winter one (UTC+1, CET). The beach
# season makes summer the real case; winter is here because a feed that is right
# only half the year is wrong.
_SUMMER_MONDAY = dt.date(2026, 8, 3)
_WINTER_MONDAY = dt.date(2027, 1, 11)


def login(client: TestClient, username: str) -> None:
    resp = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _publish(session: DbSession, roster: dict[str, User], monday: dt.date) -> None:
    week = get_or_create_week(session, monday)
    result = run_solve(session, week)
    assert result.status.value in ("optimal", "feasible")
    publish_week(session, week, roster["mattia"])
    session.commit()


def _feed(client: TestClient, token: str) -> str:
    resp = client.get("/export/ics", params={"token": token})
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/calendar")
    return resp.text


def _field(feed: str, name: str) -> list[str]:
    """Every value of an ICS field. Lines are CRLF-terminated (RFC 5545 §3.1),
    so the trailing \\r is stripped here rather than in each assertion."""
    return [value.strip() for value in re.findall(rf"^{name}:(.+)$", feed, flags=re.MULTILINE)]


def _uids(feed: str) -> list[str]:
    return _field(feed, "UID")


def _dtstarts(feed: str) -> list[str]:
    return _field(feed, "DTSTART")


# --- what the feed contains --------------------------------------------------


def test_the_feed_carries_the_owners_shifts_from_published_weeks(
    client: TestClient, session: DbSession
) -> None:
    """§7: the token owner's own assignments — and §3.3: from LOCKED weeks only.
    A second week is left `solved` (window closed, schedule computed, NOT
    published): a calendar must never leak a draft the owner cannot see in the
    app either."""
    roster = create_full_roster(session)
    _publish(session, roster, _SUMMER_MONDAY)
    # ... and an unpublished week whose schedule really does exist.
    draft = get_or_create_week(session, _SUMMER_MONDAY + dt.timedelta(weeks=1))
    run_solve(session, draft)
    session.commit()
    session.refresh(draft)
    assert draft.status is WeekStatus.SOLVED, "the draft must be solved, not published"

    pasha = roster["pasha"]
    feed = _feed(client, pasha.ics_token)
    assert feed.startswith("BEGIN:VCALENDAR")
    assert feed.rstrip().endswith("END:VCALENDAR")

    # Every event in the feed belongs to the published week: the draft week's
    # dates must not appear at all.
    draft_dates = {
        (draft.monday_date + dt.timedelta(days=offset)).strftime("%Y%m%d") for offset in range(7)
    }
    for stamp in _dtstarts(feed):
        assert stamp[:8] not in draft_dates, f"a solved-but-unpublished shift leaked: {stamp}"
    assert _dtstarts(feed), "the published week must contribute events"


def test_the_feed_is_only_the_owners_own_shifts(client: TestClient, session: DbSession) -> None:
    """§7 "per-user calendar feed": two workers' feeds differ, and each holds
    exactly its owner's rows — never the whole schedule."""
    roster = create_full_roster(session)
    _publish(session, roster, _SUMMER_MONDAY)

    pasha_uids = set(_uids(_feed(client, roster["pasha"].ics_token)))
    amir_uids = set(_uids(_feed(client, roster["amir"].ics_token)))
    assert pasha_uids and amir_uids
    assert pasha_uids != amir_uids
    assert not (pasha_uids & amir_uids), "no assignment belongs to two workers"


def test_the_feed_needs_no_session(client: TestClient, session: DbSession) -> None:
    """§7: calendar apps poll headless — the token IS the authentication, and no
    cookie is involved. (No `login()` call anywhere in this test.)"""
    roster = create_full_roster(session)
    _publish(session, roster, _SUMMER_MONDAY)
    assert not client.cookies, "precondition: this client holds no session"
    assert _feed(client, roster["amir"].ics_token)


# --- the feed is not an oracle ----------------------------------------------


@pytest.mark.parametrize("token", ["not-a-real-token", "", "   "])
def test_an_unknown_token_is_404(client: TestClient, session: DbSession, token: str) -> None:
    roster = create_full_roster(session)
    _publish(session, roster, _SUMMER_MONDAY)
    resp = client.get("/export/ics", params={"token": token})
    assert resp.status_code in (404, 422)
    if resp.status_code == 404:
        assert resp.json()["detail"] == "feed_not_found"


def test_a_deactivated_owners_valid_token_is_404(client: TestClient, session: DbSession) -> None:
    """§5: deactivation is the only removal, and it is immediate — it revokes
    open sessions, so it must revoke the headless feed too. The token is still
    correct; the account is not. Same code as an unknown token: the response
    must not tell an attacker which of the two it hit."""
    roster = create_full_roster(session)
    _publish(session, roster, _SUMMER_MONDAY)
    amir = roster["amir"]
    token = amir.ics_token
    assert _feed(client, token), "control: the feed works while the account is active"

    amir.active = False
    session.commit()

    resp = client.get("/export/ics", params={"token": token})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "feed_not_found"


# --- calendar correctness ----------------------------------------------------


def _expected_utc_hour(monday: dt.date, local_time: dt.time) -> int:
    """The UTC hour a Rome wall-clock time lands on in that week."""
    return dt.datetime.combine(monday, local_time, tzinfo=ROME).astimezone(dt.UTC).hour


@pytest.mark.parametrize(
    ("monday", "label"),
    [(_SUMMER_MONDAY, "CEST (+02:00)"), (_WINTER_MONDAY, "CET (+01:00)")],
)
def test_event_times_are_rome_wall_clock_converted_to_utc(
    client: TestClient, session: DbSession, monday: dt.date, label: str
) -> None:
    """Project convention: UTC on the wire, Europe/Rome only at the edges. The
    same 09:00 shift is 07:00Z in August and 08:00Z in January — a feed that
    ignored the offset would put every winter shift an hour wrong (`label` names
    the zone under test so a failure says which half of the year broke)."""
    roster = create_full_roster(session)
    _publish(session, roster, monday)
    feed = _feed(client, roster["amir"].ics_token)

    starts = _dtstarts(feed)
    assert starts, "the week must contribute events"
    for stamp in starts:
        assert stamp.endswith("Z"), f"DTSTART must be absolute UTC: {stamp}"

    am_hour = _expected_utc_hour(monday, settings.ics_am_start)
    pm_hour = _expected_utc_hour(monday, settings.ics_pm_start)
    seen = {int(stamp[9:11]) for stamp in starts}
    assert seen <= {am_hour, pm_hour}, (
        f"{label}: every shift must start at the AM or PM hour ({am_hour}Z/{pm_hour}Z), got {seen}"
    )


def test_uids_are_stable_across_polls(client: TestClient, session: DbSession) -> None:
    """A calendar re-polls constantly. A UID that moved would duplicate every
    event on every refresh instead of updating it in place."""
    roster = create_full_roster(session)
    _publish(session, roster, _SUMMER_MONDAY)
    token = roster["pasha"].ics_token

    first = _uids(_feed(client, token))
    second = _uids(_feed(client, token))
    assert first == second
    assert len(first) == len(set(first)), "a duplicate UID would collide in the calendar"


def test_every_event_is_well_formed(client: TestClient, session: DbSession) -> None:
    """RFC 5545 basics: CRLF lines, matched BEGIN/END, and the fields a client
    needs to render an event at all."""
    roster = create_full_roster(session)
    _publish(session, roster, _SUMMER_MONDAY)
    feed = _feed(client, roster["francesco"].ics_token)

    assert "\r\n" in feed, "content lines are CRLF-delimited"
    assert feed.count("BEGIN:VEVENT") == feed.count("END:VEVENT")
    assert feed.count("BEGIN:VEVENT") == len(_uids(feed))
    for field in ("DTSTAMP:", "DTSTART:", "DTEND:", "SUMMARY:"):
        assert feed.count(field) == feed.count("BEGIN:VEVENT"), f"every VEVENT needs {field}"


# --- the credential's blast radius (§5, §6 v1.7) -----------------------------


def test_me_carries_the_callers_own_feed_token(client: TestClient, session: DbSession) -> None:
    """§6 v1.7: `/me` is the ONE place the token is serialized — its owner
    needs the URL. This also adds the structural pin the Phase 1 review asked
    for once a field landed on MeOut: the body is exactly UserOut's fields plus
    the two /me-only additions, so a future field cannot arrive unnoticed."""
    roster = create_full_roster(session)
    login(client, "pasha")
    body = client.get("/me").json()

    assert body["ics_token"] == roster["pasha"].ics_token
    assert set(body) == set(UserOut.model_fields) | {"capabilities", "ics_token"}
    assert "is_root" not in body


def test_no_other_users_token_is_ever_serialized(client: TestClient, session: DbSession) -> None:
    """§6 v1.7 "never serialized to anyone but its own user". The root user
    listing is the widest user-shaped response in the API (§7 `/root/users`);
    if the token can leak anywhere, it leaks here."""
    create_full_roster(session)
    login(client, "matteo")  # root: sees the most
    body = client.get("/root/users").json()
    assert body, "the listing must not be empty, or this proves nothing"

    serialized = repr(body)
    assert "ics_token" not in serialized
    assert "is_root" not in serialized
    assert "password" not in serialized
