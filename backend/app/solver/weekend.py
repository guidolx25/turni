"""The fixed weekend template (H5) — the rows the solver deliberately never emits.

§H5 fixes Saturday and Sunday as a template that is *never solved*: the CP-SAT
model covers Mon–Fri only (`SOLVER_DAYS`), so someone has to produce the weekend
rows. That someone is `emit_weekend_template`, a pure function that stamps every
row `source=weekend_template` (§6 `assignments.source`).

Name-agnostic like the model (§1: the roster is passed in, never hardcoded). The
two core bagnini and the two core spiaggini are resolved by ROLE, not identity.
H5 gives the two bagnini *distinct* rotation positions (one takes Saturday AM /
Sunday PM, the other Saturday PM / Sunday AM), so a stable tiebreak is required to
split the pair: we order the core bagnini by ascending id and give the first the
Saturday-AM / Sunday-PM position. That reproduces the photographed convention
(Matteo, the lower seeded id, exits Sunday on PM) without ever reading a name.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from app.enums import (
    AssignmentRole,
    AssignmentSlot,
    AssignmentSource,
    Day,
    UserRole,
)
from app.solver.types import WorkerRef

# datetime.date.weekday(): Monday==0 … Saturday==5, Sunday==6.
_MONDAY = 0
_SATURDAY = 5


@dataclass(frozen=True)
class WeekendAssignment:
    """One fixed weekend-template slot (§H5), shaped to map onto a §6 `assignments`
    row. It is deliberately distinct from the solver's `SlotAssignment`, which is
    Mon–Fri only and carries no provenance: this row is Sat/Sun and is born stamped
    `source=weekend_template`.

    The concrete `date` (not just a `Day` enum) is carried so the continuity step
    can read each worker's Sunday `last_worked_date` for `solver_state` (§6/§8)
    straight off these rows, with no separate calendar arithmetic. The §6
    `assignments.day` enum column is derived from it via `day`.
    """

    date: dt.date
    slot: AssignmentSlot
    role: AssignmentRole
    worker_id: int
    source: AssignmentSource = AssignmentSource.WEEKEND_TEMPLATE

    @property
    def day(self) -> Day:
        """The §6 `assignments.day` value. H5 rows fall only on Sat/Sun by
        construction, so `date.weekday()` maps cleanly to one of the two."""
        return Day.SAT if self.date.weekday() == _SATURDAY else Day.SUN


def _core_by_role(roster: tuple[WorkerRef, ...], role: UserRole) -> list[WorkerRef]:
    """Core workers of a given role, ordered by ascending id — the stable,
    name-free tiebreak that splits the otherwise-symmetric bagnino pair."""
    return sorted((w for w in roster if w.is_core and w.role is role), key=lambda w: w.id)


def emit_weekend_template(
    roster: tuple[WorkerRef, ...],
    week_monday: dt.date,
) -> tuple[WeekendAssignment, ...]:
    """Emit the fixed H5 Saturday+Sunday rows for the week whose Monday is
    `week_monday`. Pure: no DB, no I/O.

    H5 exact pattern (roles resolved from the roster, never hardcoded names):

    - Saturday — bagnino[0] AM, bagnino[1] PM (bagnini); both spiaggini full-day.
    - Sunday   — bagnino[1] AM, bagnino[0] PM (bagnini); both spiaggini full-day.

    "Full-day" means a spiaggino occupies the spiaggino role in BOTH AM and PM of
    that weekend day. No Mon–Fri row is ever produced (the solver owns those, §8).
    """
    if week_monday.weekday() != _MONDAY:
        raise ValueError(f"week_monday must be a Monday, got {week_monday:%A} {week_monday}")

    bagnini = _core_by_role(roster, UserRole.BAGNINO)
    spiaggini = _core_by_role(roster, UserRole.SPIAGGINO)
    if len(bagnini) != 2 or len(spiaggini) != 2:
        # H5 is defined for exactly two core bagnini and two core spiaggini (§1).
        raise ValueError(
            f"H5 weekend template needs 2 core bagnini and 2 core spiaggini, "
            f"got {len(bagnini)} and {len(spiaggini)}"
        )

    # id-ascending: `primary` holds the Saturday-AM / Sunday-PM rotation position.
    primary, secondary = bagnini
    saturday = week_monday + dt.timedelta(days=5)
    sunday = week_monday + dt.timedelta(days=6)

    rows: list[WeekendAssignment] = [
        # Saturday bagnini (H5).
        WeekendAssignment(saturday, AssignmentSlot.AM, AssignmentRole.BAGNINO, primary.id),
        WeekendAssignment(saturday, AssignmentSlot.PM, AssignmentRole.BAGNINO, secondary.id),
        # Sunday bagnini (H5) — the AM/PM pair swaps versus Saturday.
        WeekendAssignment(sunday, AssignmentSlot.AM, AssignmentRole.BAGNINO, secondary.id),
        WeekendAssignment(sunday, AssignmentSlot.PM, AssignmentRole.BAGNINO, primary.id),
    ]
    # Spiaggini full-day (H5): the spiaggino role in both slots of both days.
    for day_date in (saturday, sunday):
        for sp in spiaggini:
            for slot in (AssignmentSlot.AM, AssignmentSlot.PM):
                rows.append(WeekendAssignment(day_date, slot, AssignmentRole.SPIAGGINO, sp.id))
    return tuple(rows)
