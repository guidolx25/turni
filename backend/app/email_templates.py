"""Bilingual email templates (spec §10 Channel 2: "templated in the user's language").

§10's payloads are **structured data** — ids, day/slot enum values, the §8 unsat
core as `{worker_id, day, slot}` items — deliberately never prose (§6
`sacrifice_proposals.conflict`). This module is where that data becomes a
sentence, and it is the *server-side* counterpart of the §9 dictionaries: the
in-app channel renders payloads in the viewer's browser, the email channel has to
render them here because there is no browser to do it.

Language follows `users.language` (§6, §9: "email language follows the user
setting"), never a global default.

**Key parity is structural.** The registry is `event -> {it: ..., en: ...}` and a
module-level guard rejects any entry missing a language at import time, so a
half-translated event cannot ship: the process refuses to start. A raised
exception rather than `assert`, because `python -O` strips asserts.

Renderers are pure functions of the payload and must never raise: a template is
downstream of a committed domain event, and a missing key is a formatting
problem, not a reason to lose a notification. Every accessor falls back.
"""

from __future__ import annotations

import datetime as dt
import html
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.enums import Language

# Sender-visible product name. Not a translatable string: it is the app's name.
APP_NAME = "Turni"


@dataclass(frozen=True)
class RenderedEmail:
    """A message body in one language, ready for `app.email.send_email`."""

    subject: str
    text: str
    html: str


# A renderer turns a payload into (subject, body paragraphs). The HTML wrapper is
# generated from the same paragraphs (`_render`), so no template writes markup
# and the two bodies can never disagree about content.
Renderer = Callable[[Mapping[str, Any]], tuple[str, list[str]]]


# --- localization primitives (§9 does this with Intl; the server needs its own) ---

_DAY_NAMES: dict[Language, dict[str, str]] = {
    Language.IT: {
        "mon": "lunedì",
        "tue": "martedì",
        "wed": "mercoledì",
        "thu": "giovedì",
        "fri": "venerdì",
        "sat": "sabato",
        "sun": "domenica",
    },
    Language.EN: {
        "mon": "Monday",
        "tue": "Tuesday",
        "wed": "Wednesday",
        "thu": "Thursday",
        "fri": "Friday",
        "sat": "Saturday",
        "sun": "Sunday",
    },
}

# §6 constraints.slot spans `full_day`; assignments.slot does not. One table
# covers both so a template never has to know which enum produced the value.
_SLOT_NAMES: dict[Language, dict[str, str]] = {
    Language.IT: {"am": "mattina", "pm": "pomeriggio", "full_day": "giornata intera"},
    Language.EN: {"am": "morning", "pm": "afternoon", "full_day": "full day"},
}

# Mirrors the §9 dictionaries' `role.*` keys: the roles are Italian job titles and
# stay untranslated in IT, but EN readers get the occupation.
_ROLE_NAMES: dict[Language, dict[str, str]] = {
    Language.IT: {"bagnino": "bagnino", "spiaggino": "spiaggino", "jolly": "jolly"},
    Language.EN: {"bagnino": "lifeguard", "spiaggino": "beach worker", "jolly": "jolly"},
}

_MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _text(payload: Mapping[str, Any], key: str) -> str | None:
    """A payload value as a string, or None when absent/null."""
    value = payload.get(key)
    return None if value is None else str(value)


def day_name(value: str | None, language: Language) -> str:
    """A §6 day enum value in `language`; the raw value if it is not one."""
    if value is None:
        return "?"
    return _DAY_NAMES[language].get(value, value)


def slot_name(value: str | None, language: Language) -> str:
    if value is None:
        return "?"
    return _SLOT_NAMES[language].get(value, value)


def role_name(value: str | None, language: Language) -> str:
    if value is None:
        return "?"
    return _ROLE_NAMES[language].get(value, value)


def date_label(iso_date: str | None, language: Language) -> str:
    """An ISO date as a human date. IT `13/07/2026`; EN `13 July 2026`.

    Payloads carry ISO strings (`week.monday_date.isoformat()`), which is the
    right wire format and the wrong thing to put in a sentence. Unparseable input
    is echoed rather than raising — see the module docstring.
    """
    if iso_date is None:
        return "?"
    try:
        parsed = dt.date.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    if language is Language.IT:
        return f"{parsed.day:02d}/{parsed.month:02d}/{parsed.year}"
    return f"{parsed.day} {_MONTHS_EN[parsed.month - 1]} {parsed.year}"


def _week_label(payload: Mapping[str, Any], language: Language) -> str:
    """Every §10 payload names its week by the §6 natural key (Monday's date)."""
    return date_label(_text(payload, "week"), language)


def _assignment_label(value: Any, language: Language) -> str:
    """One `{id, day, slot, role}` swap side as `venerdì pomeriggio (bagnino)`."""
    if not isinstance(value, Mapping):
        return "?"
    day = day_name(_text(value, "day"), language)
    slot = slot_name(_text(value, "slot"), language)
    role = role_name(_text(value, "role"), language)
    return f"{day} {slot} ({role})"


# Reserved payload key carrying `{user_id: display_name}`, injected by `render`
# from the caller's DB session. It is NOT part of the stored §6 payload — the
# in-app channel resolves names in the browser, so persisting them would
# denormalize a name that can later change.
NAMES_KEY = "_names"


def person_name(payload: Mapping[str, Any], user_id: Any, language: Language) -> str:
    """A worker's display name for the body text, or a neutral fallback.

    Email cannot do what the in-app channel does — look the id up client-side —
    so `render` injects the names it resolved. Falling back to "a colleague"
    rather than to "#7": in a five-person team an unresolved id reads as a bug,
    and a vaguer sentence is better than a wrong-looking one.
    """
    names = payload.get(NAMES_KEY)
    if isinstance(names, Mapping):
        name = names.get(user_id)
        if isinstance(name, str) and name:
            return name
    return "un collega" if language is Language.IT else "a colleague"


def _conflict_lines(payload: Mapping[str, Any], language: Language) -> list[str]:
    """The §8 minimal unsat core as bullet lines.

    Items are `{worker_id, day, slot}` (§6) — ids, because the STORED payload is
    data (never prose, so the in-app channel can localize it). Names are resolved
    for this rendering only, via `person_name`.
    """
    conflict = payload.get("conflict")
    if not isinstance(conflict, Sequence) or isinstance(conflict, str | bytes):
        return []
    lines: list[str] = []
    for item in conflict:
        if not isinstance(item, Mapping):
            continue
        who = person_name(payload, item.get("worker_id"), language)
        day = day_name(_text(item, "day"), language)
        slot = slot_name(_text(item, "slot"), language)
        lines.append(f"- {who}: {day} {slot}")
    return lines


_ESCALATION_OUTCOME: dict[Language, dict[str, str]] = {
    Language.IT: {
        "declined": "la proposta di spostare il giorno libero è stata rifiutata",
        "escalated": "nessuno spostamento del giorno libero risolve il conflitto",
    },
    Language.EN: {
        "declined": "the free-day move was declined",
        "escalated": "no free-day move resolves the conflict",
    },
}


def _escalation_reason(payload: Mapping[str, Any], language: Language) -> str:
    outcome = _text(payload, "outcome") or ""
    return _ESCALATION_OUTCOME[language].get(outcome, outcome or "?")


# --- templates, one function per (event, language) ---------------------------


def _published_it(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    week = _week_label(p, Language.IT)
    return (
        f"Turni pubblicati — settimana del {week}",
        [
            f"Il turno della settimana del {week} è stato pubblicato.",
            "Puoi consultarlo nell'app.",
        ],
    )


def _published_en(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    week = _week_label(p, Language.EN)
    return (
        f"Schedule published — week of {week}",
        [
            f"The schedule for the week of {week} has been published.",
            "You can view it in the app.",
        ],
    )


def _swap_requested_it(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    return (
        "Richiesta di scambio turno",
        [
            f"{person_name(p, p.get('from_user'), Language.IT)} ti ha proposto uno "
            f"scambio di turno per la settimana del {_week_label(p, Language.IT)}.",
            f"Il suo turno: {_assignment_label(p.get('from_assignment'), Language.IT)}.",
            f"Il tuo turno: {_assignment_label(p.get('to_assignment'), Language.IT)}.",
            "Hai 48 ore per accettare o rifiutare nell'app; "
            "dopo la richiesta scade automaticamente.",
        ],
    )


def _swap_requested_en(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    return (
        "Shift swap request",
        [
            f"{person_name(p, p.get('from_user'), Language.EN)} has asked to swap "
            f"shifts with you for the week of {_week_label(p, Language.EN)}.",
            f"Their shift: {_assignment_label(p.get('from_assignment'), Language.EN)}.",
            f"Your shift: {_assignment_label(p.get('to_assignment'), Language.EN)}.",
            "You have 48 hours to accept or decline in the app; "
            "after that the request expires automatically.",
        ],
    )


def _swap_accepted_it(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    # Neutral phrasing: §4 sends this to BOTH parties and to the visible admins,
    # so no "your shift" is correct for every recipient.
    return (
        "Scambio turno accettato",
        [
            f"Uno scambio di turno per la settimana del {_week_label(p, Language.IT)} "
            "è stato accettato.",
            f"Turni scambiati: {_assignment_label(p.get('from_assignment'), Language.IT)} "
            f"e {_assignment_label(p.get('to_assignment'), Language.IT)}.",
            "Il turno aggiornato è visibile nell'app.",
        ],
    )


def _swap_accepted_en(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    return (
        "Shift swap accepted",
        [
            f"A shift swap for the week of {_week_label(p, Language.EN)} has been accepted.",
            f"Shifts exchanged: {_assignment_label(p.get('from_assignment'), Language.EN)} "
            f"and {_assignment_label(p.get('to_assignment'), Language.EN)}.",
            "The updated schedule is visible in the app.",
        ],
    )


def _swap_rejected_it(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    return (
        "Scambio turno rifiutato",
        [
            "La tua richiesta di scambio per la settimana del "
            f"{_week_label(p, Language.IT)} è stata rifiutata.",
            f"Riguardava: {_assignment_label(p.get('from_assignment'), Language.IT)} "
            f"e {_assignment_label(p.get('to_assignment'), Language.IT)}.",
            "Il turno resta invariato.",
        ],
    )


def _swap_rejected_en(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    return (
        "Shift swap declined",
        [
            f"Your swap request for the week of {_week_label(p, Language.EN)} was declined.",
            f"It concerned: {_assignment_label(p.get('from_assignment'), Language.EN)} "
            f"and {_assignment_label(p.get('to_assignment'), Language.EN)}.",
            "The schedule is unchanged.",
        ],
    )


def _sacrifice_proposed_it(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    day = day_name(_text(p, "proposed_free_day"), Language.IT)
    return (
        "Richiesta: sposta il tuo giorno libero",
        [
            f"Per coprire tutti i turni della settimana del {_week_label(p, Language.IT)} "
            f"ti chiediamo di spostare il tuo giorno libero a {day}.",
            "Nulla viene modificato finché non rispondi: apri l'app per accettare o rifiutare.",
        ],
    )


def _sacrifice_proposed_en(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    day = day_name(_text(p, "proposed_free_day"), Language.EN)
    return (
        "Request: move your free day",
        [
            f"To cover every shift in the week of {_week_label(p, Language.EN)} "
            f"we are asking you to move your free day to {day}.",
            "Nothing changes until you answer: open the app to accept or decline.",
        ],
    )


def _sacrifice_resolved_it(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    day = day_name(_text(p, "free_day"), Language.IT)
    week = _week_label(p, Language.IT)
    return (
        "Giorno libero aggiornato",
        [
            f"Il tuo giorno libero per la settimana del {week} è ora {day}.",
            f"Il turno della settimana del {week} è stato ricalcolato e pubblicato.",
        ],
    )


def _sacrifice_resolved_en(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    day = day_name(_text(p, "free_day"), Language.EN)
    week = _week_label(p, Language.EN)
    return (
        "Free day updated",
        [
            f"Your free day for the week of {week} is now {day}.",
            f"The schedule for the week of {week} has been re-solved and published.",
        ],
    )


def _sacrifice_escalated_it(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    week = _week_label(p, Language.IT)
    body = [
        f"La settimana del {week} non è stata pubblicata: {_escalation_reason(p, Language.IT)}.",
    ]
    lines = _conflict_lines(p, Language.IT)
    if lines:
        body.append("Richieste vincolanti in conflitto:\n" + "\n".join(lines))
    body.append("La settimana resta da risolvere e non è visibile ai lavoratori.")
    return (f"Conflitto da risolvere — settimana del {week}", body)


def _sacrifice_escalated_en(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    week = _week_label(p, Language.EN)
    body = [
        f"The week of {week} was not published: {_escalation_reason(p, Language.EN)}.",
    ]
    lines = _conflict_lines(p, Language.EN)
    if lines:
        body.append("Conflicting hard requests:\n" + "\n".join(lines))
    body.append("The week is still unresolved and is not visible to workers.")
    return (f"Conflict to resolve — week of {week}", body)


def _weekend_hard_it(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    who = _text(p, "display_name") or f"#{_text(p, 'user_id') or '?'}"
    day = day_name(_text(p, "day"), Language.IT)
    slot = slot_name(_text(p, "slot"), Language.IT)
    return (
        "Indisponibilità vincolante nel weekend",
        [
            f"{who} ha inserito un'indisponibilità vincolante per {day} ({slot}) "
            f"nella settimana del {_week_label(p, Language.IT)}.",
            "Il weekend segue un turno fisso e non viene calcolato dal solver, "
            "quindi questa richiesta va gestita manualmente.",
        ],
    )


def _weekend_hard_en(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    who = _text(p, "display_name") or f"#{_text(p, 'user_id') or '?'}"
    day = day_name(_text(p, "day"), Language.EN)
    slot = slot_name(_text(p, "slot"), Language.EN)
    return (
        "Hard weekend unavailability",
        [
            f"{who} submitted a hard unavailability for {day} ({slot}) "
            f"in the week of {_week_label(p, Language.EN)}.",
            "The weekend is a fixed template and is not solved, "
            "so this request has to be handled manually.",
        ],
    )


def _window_closing_it(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    week = _week_label(p, Language.IT)
    return (
        f"Ultimo giorno per i vincoli — settimana del {week}",
        [
            f"Le richieste per la settimana del {week} si chiudono domani, domenica alle 17:00.",
            "Fino ad allora puoi ancora inserire o modificare i tuoi vincoli nell'app.",
        ],
    )


def _window_closing_en(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    week = _week_label(p, Language.EN)
    return (
        f"Last day for requests — week of {week}",
        [
            f"Requests for the week of {week} close tomorrow, Sunday at 17:00.",
            "Until then you can still add or edit your constraints in the app.",
        ],
    )


def _admin_override_it(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    # §5 override. The payload is written by the Phase 6 override endpoint; the
    # slot fields are read defensively so a payload without them still sends.
    slot = _assignment_label(p, Language.IT) if p.get("day") else None
    detail = f" ({slot})" if slot else ""
    return (
        "Turno modificato da un amministratore",
        [
            f"Un amministratore ha modificato il turno della settimana del "
            f"{_week_label(p, Language.IT)}{detail}.",
            "Controlla il turno aggiornato nell'app.",
        ],
    )


def _admin_override_en(p: Mapping[str, Any]) -> tuple[str, list[str]]:
    slot = _assignment_label(p, Language.EN) if p.get("day") else None
    detail = f" ({slot})" if slot else ""
    return (
        "Schedule changed by an administrator",
        [
            f"An administrator changed the schedule for the week of "
            f"{_week_label(p, Language.EN)}{detail}.",
            "Check your updated shifts in the app.",
        ],
    )


# --- registry ----------------------------------------------------------------

# §10's event list, each with BOTH languages. The nested dict shape plus the guard
# below is what makes a single-language event unrepresentable in a running process.
_TEMPLATES: dict[str, dict[Language, Renderer]] = {
    "schedule_published": {Language.IT: _published_it, Language.EN: _published_en},
    "swap_requested": {Language.IT: _swap_requested_it, Language.EN: _swap_requested_en},
    "swap_accepted": {Language.IT: _swap_accepted_it, Language.EN: _swap_accepted_en},
    "swap_rejected": {Language.IT: _swap_rejected_it, Language.EN: _swap_rejected_en},
    "sacrifice_proposed": {
        Language.IT: _sacrifice_proposed_it,
        Language.EN: _sacrifice_proposed_en,
    },
    "sacrifice_resolved": {
        Language.IT: _sacrifice_resolved_it,
        Language.EN: _sacrifice_resolved_en,
    },
    "sacrifice_escalated": {
        Language.IT: _sacrifice_escalated_it,
        Language.EN: _sacrifice_escalated_en,
    },
    "weekend_hard_escalated": {Language.IT: _weekend_hard_it, Language.EN: _weekend_hard_en},
    "window_closing_24h": {Language.IT: _window_closing_it, Language.EN: _window_closing_en},
    "admin_override": {Language.IT: _admin_override_it, Language.EN: _admin_override_en},
}

SUPPORTED_EVENTS = frozenset(_TEMPLATES)


def _assert_language_parity() -> None:
    """Refuse to import with a half-translated event (§10).

    An explicit raise, not `assert`: `python -O` strips asserts, and this guard
    has to hold in production — where a missing translation means a worker
    silently gets no email.
    """
    for event, by_language in _TEMPLATES.items():
        missing = {lang for lang in Language} - set(by_language)
        if missing:
            names = ", ".join(sorted(lang.value for lang in missing))
            raise RuntimeError(f"email template '{event}' is missing language(s): {names}")


_assert_language_parity()


def _to_html(subject: str, paragraphs: list[str]) -> str:
    """A minimal HTML body generated from the text paragraphs.

    Deliberately unstyled: §10 asks for templated mail, not a designed one, and
    an inline-CSS layout would be a second body to keep in sync with the text.
    Everything is escaped — payload values reach here (`display_name` is
    user-supplied) and must never be able to inject markup.
    """
    blocks = "".join(
        f"<p>{html.escape(paragraph).replace(chr(10), '<br>')}</p>" for paragraph in paragraphs
    )
    return f"<html><body><h2>{html.escape(subject)}</h2>{blocks}</body></html>"


def render(
    event_type: str,
    language: Language,
    payload: Mapping[str, Any] | None,
    names: Mapping[int, str] | None = None,
) -> RenderedEmail | None:
    """The §10 email body for `event_type` in `language`, or None if no template.

    None is a legitimate answer: `notifications.event_type` is free text (§6) so
    an event can exist with in-app delivery only. The caller logs and moves on
    rather than treating it as an error.

    `names` maps the user ids this payload references to display names. The
    caller resolves them (it has the session; this module stays pure) and they
    are merged into a COPY under `NAMES_KEY` — the stored §6 payload is never
    touched, so a later rename does not leave stale prose in the notifications
    table.
    """
    by_language = _TEMPLATES.get(event_type)
    if by_language is None:
        return None
    payload = dict(payload or {})
    if names:
        payload[NAMES_KEY] = dict(names)
    subject, paragraphs = by_language[language](payload)
    prefixed = f"{APP_NAME} — {subject}"
    return RenderedEmail(
        subject=prefixed,
        text="\n\n".join(paragraphs),
        html=_to_html(prefixed, paragraphs),
    )
