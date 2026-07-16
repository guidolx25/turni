"""Cross-week solver_state continuity — the §2.2 "boundary with the previous week".

S2's alternation penalty runs across the Sunday→Monday boundary (§2.2): each
worker's last worked slot seeds next week's Monday. §8 persists this as
`solver_state(last_worked_slot, last_worked_date)` and the solver reads it back as
`SolverInput.prior_state: Mapping[int, PriorSlot]`. `compute_next_solver_state`
is the pure *compute* half — deriving both shapes from a week's weekend template.
The *persist* half (writing the rows at publish) is Phase 3, out of scope here.

Only SUNDAY seeds the Monday boundary: Sunday is the last day worked before the
next Monday, so Saturday (and any Mon–Fri) rows are irrelevant to continuity.

The FULL_DAY case is the reason the two shapes are not interchangeable. Pasha and
Amir work Sunday full-day, but `solver_state.last_worked_slot` is a single
nullable am/pm ENUM (§6) and cannot store "both". So for them the column stays
NULL and the FULL_DAY boundary is DERIVED from the weekend template into
`PriorSlot.FULL_DAY` (see the `PriorSlot` docstring). Matteo exits Sunday PM,
Francesco Sunday AM; Mattia never works the weekend (§H5) and is therefore absent
from the mapping — no boundary term at all.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

from app.enums import AssignmentSlot, Day
from app.solver.types import PriorSlot
from app.solver.weekend import WeekendAssignment


@dataclass(frozen=True)
class WorkerContinuity:
    """One worker's Sunday→Monday boundary, in both shapes §8 needs at once:

    - `last_worked_slot` / `last_worked_date`: storable verbatim in §6
      `solver_state`. `last_worked_slot` is None for a full-day worker, because the
      single am/pm column cannot represent "both" (§6) — the boundary lives in
      `prior_slot` instead.
    - `prior_slot`: the wider `PriorSlot` (AM/PM/FULL_DAY) the solver consumes via
      `SolverInput.prior_state`.
    """

    worker_id: int
    last_worked_date: dt.date
    last_worked_slot: AssignmentSlot | None
    prior_slot: PriorSlot


def compute_next_solver_state(
    weekend: tuple[WeekendAssignment, ...],
) -> tuple[WorkerContinuity, ...]:
    """Derive each worker's Sunday→Monday continuity from the weekend template.
    Pure: no DB, no I/O.

    A worker with no Sunday rows (the jolly, §H5) is absent from the result — no
    boundary term. Results are ordered by worker id for determinism.
    """
    sunday_slots: dict[int, set[AssignmentSlot]] = defaultdict(set)
    sunday_date: dict[int, dt.date] = {}
    for a in weekend:
        # Only Sunday seeds the next Monday (§2.2). Saturday is ignored.
        if a.day is not Day.SUN:
            continue
        sunday_slots[a.worker_id].add(a.slot)
        sunday_date[a.worker_id] = a.date

    records: list[WorkerContinuity] = []
    for wid in sorted(sunday_slots):
        slots = sunday_slots[wid]
        if slots == {AssignmentSlot.AM, AssignmentSlot.PM}:
            # Full-day: column stays NULL, boundary carried by PriorSlot (§6).
            prior_slot, last_slot = PriorSlot.FULL_DAY, None
        elif slots == {AssignmentSlot.AM}:
            prior_slot, last_slot = PriorSlot.AM, AssignmentSlot.AM
        elif slots == {AssignmentSlot.PM}:
            prior_slot, last_slot = PriorSlot.PM, AssignmentSlot.PM
        else:
            raise ValueError(f"worker {wid} has an impossible Sunday slot set: {slots}")
        records.append(
            WorkerContinuity(
                worker_id=wid,
                last_worked_date=sunday_date[wid],
                last_worked_slot=last_slot,
                prior_slot=prior_slot,
            )
        )
    return tuple(records)


def as_prior_state(continuity: tuple[WorkerContinuity, ...]) -> dict[int, PriorSlot]:
    """Project continuity records onto the `SolverInput.prior_state` mapping
    (§8). Workers absent from `continuity` stay absent here — no boundary term."""
    return {c.worker_id: c.prior_slot for c in continuity}
