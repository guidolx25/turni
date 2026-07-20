"""ICS calendar feed (spec §7 `GET /export/ics`, v1.7).

Deliberately NOT behind the session cookie: calendar apps poll the URL headless,
so the credential is the per-user `users.ics_token` (§6 v1.7) carried as a query
parameter and compared in constant time (§7). Unknown, wrong and inactive all
collapse into one 404 — the response must not be an oracle for which case it was.

Visibility keys off `locked`, never `solved` (§3.3): the feed contains a VEVENT
per assignment of the token's owner in PUBLISHED weeks only — a calendar must
never leak a draft schedule the owner cannot see in the app either.

Times: the DB knows only (day, slot); the concrete wall-clock hours come from
deploy-time settings (§11, provisional defaults) as Europe/Rome local time and
are converted to UTC here at the edge (project convention: UTC on the wire,
Rome only at the edges). UTC `DTSTART`/`DTEND` (`...Z`) instead of a VTIMEZONE
block: simpler and equally correct, since the instants are already absolute.
"""

from __future__ import annotations

import datetime as dt
import hmac
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from app.config import settings
from app.db import utcnow
from app.deps import DbDep
from app.enums import AssignmentSlot, Day, WeekStatus
from app.models import Assignment, User, Week

router = APIRouter(tags=["ics"])

# One code for every failure mode: no such token, inactive owner (§5: a
# deactivated user's feed dies with their sessions), malformed value.
ERROR_FEED_NOT_FOUND = "feed_not_found"

# Calendar offsets from the week's Monday (§6 weeks.monday_date).
_DAY_OFFSET: dict[Day, int] = {d: i for i, d in enumerate(Day)}

_CRLF = "\r\n"  # RFC 5545 §3.1: content lines are CRLF-delimited


@router.get("/export/ics")
def export_ics(
    db: DbDep,
    token: str = Query(min_length=1, max_length=128),
) -> Response:
    """§7: the token owner's personal feed — their assignments in locked weeks."""
    user = db.scalar(select(User).where(User.ics_token == token, User.active.is_(True)))
    # §7: constant-time comparison is the authorization decision. The indexed
    # lookup above only *finds* the candidate row; `compare_digest` is what
    # accepts the credential, so the accept/reject step never leaks timing.
    if user is None or not hmac.compare_digest(user.ics_token.encode(), token.encode()):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_FEED_NOT_FOUND)

    rows = db.execute(
        select(Assignment, Week)
        .join(Week, Assignment.week_id == Week.id)
        .where(Assignment.user_id == user.id, Week.status == WeekStatus.LOCKED)
    ).all()
    ordered = sorted(
        rows, key=lambda r: (r.Week.monday_date, _DAY_OFFSET[r.Assignment.day], r.Assignment.slot)
    )

    stamp = _fmt_utc(utcnow())
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Turni//Turni//IT",
        "CALSCALE:GREGORIAN",
    ]
    for row in ordered:
        assignment, week = row.Assignment, row.Week
        start, end = _event_bounds(week.monday_date, assignment.day, assignment.slot)
        # SUMMARY is data-ish and language-neutral by construction: the role
        # values are §1's Italian domain words (bagnino/spiaggino — names, not
        # translatable strings), the slot is AM/PM. No i18n dictionary applies to
        # a calendar feed, so nothing here may need translating.
        summary = f"Turni — {assignment.role.value} {assignment.slot.value.upper()}"
        lines += [
            "BEGIN:VEVENT",
            # Stable per assignment row, so a re-poll updates events in place
            # instead of duplicating them.
            f"UID:turni-{assignment.id}@turni",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_fmt_utc(start)}",
            f"DTEND:{_fmt_utc(end)}",
            f"SUMMARY:{_escape(summary)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")

    # Lines are short by construction (UID/SUMMARY are bounded), so no 75-octet
    # folding pass is needed — nothing here can approach the limit.
    return Response(
        content=_CRLF.join(lines) + _CRLF,
        media_type="text/calendar; charset=utf-8",
    )


def _event_bounds(
    monday: dt.date, day: Day, slot: AssignmentSlot
) -> tuple[dt.datetime, dt.datetime]:
    """The slot's absolute start/end: Europe/Rome wall clock (deploy-time §11
    settings) on the assignment's calendar date, converted to UTC at this edge."""
    date = monday + dt.timedelta(days=_DAY_OFFSET[day])
    if slot is AssignmentSlot.AM:
        start_t, end_t = settings.ics_am_start, settings.ics_am_end
    else:
        start_t, end_t = settings.ics_pm_start, settings.ics_pm_end
    tz = ZoneInfo(settings.tz)
    start = dt.datetime.combine(date, start_t, tzinfo=tz).astimezone(dt.UTC)
    end = dt.datetime.combine(date, end_t, tzinfo=tz).astimezone(dt.UTC)
    return start, end


def _fmt_utc(moment: dt.datetime) -> str:
    """RFC 5545 UTC date-time form (`19970714T173000Z`)."""
    return moment.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    """RFC 5545 §3.3.11 TEXT escaping: backslash first, then the specials."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
