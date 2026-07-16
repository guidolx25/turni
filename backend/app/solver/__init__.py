"""CP-SAT scheduling solver (spec §8).

The public boundary is the pure function `solve(SolverInput) -> SolverResult`
and the value types it consumes and returns. Everything the solver needs is
carried in `SolverInput`; it performs no DB access and no I/O (§8: pure model).
"""

from __future__ import annotations

from app.solver.types import (
    ObjectiveBreakdown,
    PersonalConstraint,
    PriorSlot,
    SlotAssignment,
    SolverInput,
    SolverResult,
    SolverStatus,
    Weights,
    WorkerRef,
    solve,
)

__all__ = [
    "ObjectiveBreakdown",
    "PersonalConstraint",
    "PriorSlot",
    "SlotAssignment",
    "SolverInput",
    "SolverResult",
    "SolverStatus",
    "Weights",
    "WorkerRef",
    "solve",
]
