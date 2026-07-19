"""Enum types for the §6 data model.

Every member's *value* is the lowercase string the spec writes ('am', 'bagnino',
'weekend_template', ...); those values are what reach the DB (see
`app.db.enum_column`) and what the API will emit, so they are part of the
contract, not an implementation detail.

`UserRole`/`AssignmentRole` and `ConstraintSlot`/`AssignmentSlot` are
deliberately separate pairs: §6 gives them different value sets and collapsing
them would let an impossible value through the type layer.
"""

from __future__ import annotations

import enum


class UserRole(enum.StrEnum):
    """§6 users.role — 'jolly' (Mattia) is compatible with both worked roles."""

    BAGNINO = "bagnino"
    SPIAGGINO = "spiaggino"
    JOLLY = "jolly"


class Language(enum.StrEnum):
    """§6 users.language — also selects the email template language (§10)."""

    IT = "it"
    EN = "en"


class WeekStatus(enum.StrEnum):
    """§6 weeks.status — the three §3 lifecycle states, in lifecycle order.

    - open   = submission window open, constraints editable (§3.1).
    - solved = window closed, solver has run; schedule computed but NOT yet
               visible/published, OR a §2.3 sacrifice is pending. Reached by a
               manual "Generate now" (awaits review) or by any solve that opens
               the sacrifice flow. Visibility and fan-out never key off this
               state — only `locked` (§3.2/§3.3).
    - locked = published: schedule visible to all, slots locked, fan-out done (§3.3).
    """

    OPEN = "open"
    SOLVED = "solved"
    LOCKED = "locked"


class Day(enum.StrEnum):
    """§6 constraints.day — mon..sun.

    Spans the weekend even though the solver only covers Mon–Fri (H5): a worker
    can still express an unavailability on a template day.
    """

    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


class ConstraintSlot(enum.StrEnum):
    """§6 constraints.slot — includes 'full_day' (a day-level unavailability, H7).

    Distinct from `AssignmentSlot`: an assignment is always a concrete AM or PM
    slot, never a full day.
    """

    AM = "am"
    PM = "pm"
    FULL_DAY = "full_day"


class AssignmentSlot(enum.StrEnum):
    """§6 assignments.slot and solver_state.last_worked_slot — the real slots."""

    AM = "am"
    PM = "pm"


class ConstraintKind(enum.StrEnum):
    """§6 constraints.kind — 'hard' is H7, 'soft' is the S1 objective term."""

    HARD = "hard"
    SOFT = "soft"


class AssignmentRole(enum.StrEnum):
    """§6 assignments.role — the role actually worked in a slot (no 'jolly')."""

    BAGNINO = "bagnino"
    SPIAGGINO = "spiaggino"


class AssignmentSource(enum.StrEnum):
    """§6 assignments.source — provenance of the row (§3 lifecycle, §4 swaps)."""

    SOLVER = "solver"
    WEEKEND_TEMPLATE = "weekend_template"
    SWAP = "swap"
    OVERRIDE = "override"


class SwapStatus(enum.StrEnum):
    """§6 swap_requests.status — the §4 state machine.

    pending → accepted/rejected/expired(48 h) → (pending_admin if
    REQUIRE_ADMIN_APPROVAL) → applied.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    PENDING_ADMIN = "pending_admin"
    APPLIED = "applied"


class SacrificeStatus(enum.StrEnum):
    """§6 sacrifice_proposals.status — §2.3 requires an explicit accept/decline."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
