"""CP-SAT scheduling solver (spec §8).

The public boundary is the pure function `solve(SolverInput) -> SolverResult`
and the value types it consumes and returns. Everything the solver needs is
carried in `SolverInput`; it performs no DB access and no I/O (§8: pure model).
"""

from __future__ import annotations

from app.solver.continuity import (
    WorkerContinuity,
    as_prior_state,
    compute_next_solver_state,
)
from app.solver.types import (
    FREE_DAYS,
    SOLVER_DAYS,
    ObjectiveBreakdown,
    PersonalConstraint,
    PriorSlot,
    SlotAssignment,
    SolverInput,
    SolverResult,
    SolverStatus,
    Weights,
    WorkerRef,
    free_day_domain,
    solve,
)
from app.solver.weekend import (
    WeekendAssignment,
    emit_weekend_template,
    full_weekend_worker_ids,
)

__all__ = [
    "FREE_DAYS",
    "SOLVER_DAYS",
    "ObjectiveBreakdown",
    "PersonalConstraint",
    "PriorSlot",
    "SlotAssignment",
    "SolverInput",
    "SolverResult",
    "SolverStatus",
    "WeekendAssignment",
    "Weights",
    "WorkerContinuity",
    "WorkerRef",
    "as_prior_state",
    "compute_next_solver_state",
    "emit_weekend_template",
    "free_day_domain",
    "full_weekend_worker_ids",
    "solve",
]
