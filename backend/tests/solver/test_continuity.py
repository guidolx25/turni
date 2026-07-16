"""Cross-week solver_state continuity (§2.2/§8) — pure, no DB.

The correctness oracle is `fixtures.canonical_prior_state()`: the prior_state the
solver suite hand-builds today. `compute_next_solver_state` fed the H5 weekend
template MUST reproduce it exactly, and the storable slot/date fields must match
§6 `solver_state` (Matteo Sunday PM, Francesco Sunday AM, NULL slot for the
full-day spiaggini, Mattia absent entirely).
"""

from __future__ import annotations

import datetime as dt

from app.enums import AssignmentSlot
from app.solver.continuity import as_prior_state, compute_next_solver_state
from app.solver.types import PriorSlot
from app.solver.weekend import emit_weekend_template
from tests.solver.fixtures import (
    AMIR,
    FRANCESCO,
    MATTEO,
    MATTIA,
    PASHA,
    WEEK_MONDAY,
    canonical_prior_state,
    roster,
)

SUNDAY = WEEK_MONDAY + dt.timedelta(days=6)


def _continuity() -> dict[int, object]:
    weekend = emit_weekend_template(roster(), WEEK_MONDAY)
    return {c.worker_id: c for c in compute_next_solver_state(weekend)}


def test_prior_state_matches_the_canonical_oracle() -> None:
    weekend = emit_weekend_template(roster(), WEEK_MONDAY)
    prior = as_prior_state(compute_next_solver_state(weekend))
    assert prior == canonical_prior_state()


def test_single_slot_workers_are_storable_verbatim() -> None:
    by_id = _continuity()
    # Matteo exits Sunday PM, Francesco Sunday AM (§8): storable slot + date.
    assert by_id[MATTEO].prior_slot is PriorSlot.PM
    assert by_id[MATTEO].last_worked_slot is AssignmentSlot.PM
    assert by_id[MATTEO].last_worked_date == SUNDAY

    assert by_id[FRANCESCO].prior_slot is PriorSlot.AM
    assert by_id[FRANCESCO].last_worked_slot is AssignmentSlot.AM
    assert by_id[FRANCESCO].last_worked_date == SUNDAY


def test_full_day_workers_keep_the_slot_column_null() -> None:
    by_id = _continuity()
    # Pasha and Amir work Sunday full-day: the single am/pm column cannot hold
    # "both" (§6), so it stays None and the boundary lives in prior_slot.
    for wid in (PASHA, AMIR):
        assert by_id[wid].prior_slot is PriorSlot.FULL_DAY
        assert by_id[wid].last_worked_slot is None
        assert by_id[wid].last_worked_date == SUNDAY


def test_jolly_is_absent_no_boundary_term() -> None:
    weekend = emit_weekend_template(roster(), WEEK_MONDAY)
    records = compute_next_solver_state(weekend)
    # Mattia never works the weekend (§H5): absent from both shapes.
    assert MATTIA not in {c.worker_id for c in records}
    assert MATTIA not in as_prior_state(records)
