"""Solver input/output value types — the pure function boundary of §8.

The solver is a **pure function** `solve(SolverInput) -> SolverResult`: it reads
only the dataclass it is handed and returns assignments plus diagnostics. No DB
access, no I/O, no global state — an adapter (Phase 3) maps §6 rows onto these
types and back. Everything here is frozen so an input can be logged and replayed.

Naming: the solver's output row is `SlotAssignment`, deliberately distinct from
the §6 `assignments` ORM row (`app.models.Assignment`), because the solver only
ever emits Mon–Fri worked slots (§8: weekend is a template, never solved).
"""

from __future__ import annotations

import datetime as dt
import enum
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.enums import (
    AssignmentRole,
    AssignmentSlot,
    ConstraintKind,
    ConstraintSlot,
    Day,
    UserRole,
)

# §8: the solver domain is Mon–Fri only. Saturday/Sunday are the fixed weekend
# template (H5) and never appear as a variable, an input day, or an output row.
SOLVER_DAYS: tuple[Day, ...] = (Day.MON, Day.TUE, Day.WED, Day.THU, Day.FRI)

# H3: a core worker's free day is one of Mon–Thu (never Fri, never the weekend).
FREE_DAYS: tuple[Day, ...] = (Day.MON, Day.TUE, Day.WED, Day.THU)


class SolverStatus(enum.StrEnum):
    """Outcome of a solve. OPTIMAL/FEASIBLE carry an objective breakdown;
    INFEASIBLE carries the blocking hard constraints instead (§2.3)."""

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"


class PriorSlot(enum.StrEnum):
    """The slot(s) a worker worked on the day immediately before this Monday,
    seeding S2's cross-week alternation (§2.2: "including the boundary with the
    previous week").

    Three explicit cases, plus a fourth expressed by *absence* from
    `SolverInput.prior_state`:

    - absent  → no boundary: a first-ever week with no prior state (a legal input).
    - AM / PM → a single worked slot (Francesco exits Sunday AM, Matteo Sunday PM).
    - FULL_DAY → both slots worked (Pasha and Amir work Sunday full-day, so their
      Monday alternation break is unavoidable in either direction).

    This is intentionally *wider* than `AssignmentSlot`: `solver_state.last_worked_slot`
    is a single nullable am/pm ENUM and cannot store "both", so the adapter supplies
    the FULL_DAY boundary from the weekend template, not from that column.
    """

    AM = "am"
    PM = "pm"
    FULL_DAY = "full_day"


@dataclass(frozen=True)
class WorkerRef:
    """A worker as the solver sees them — a stable id plus role and flags. Names
    are never hardcoded in the model (§1 roster is passed in via `SolverInput`).

    `is_core` marks the four workers with an H3 free day (Matteo, Francesco,
    Pasha, Amir); `is_jolly` marks the single swing worker (Mattia), whom H6
    fills open slots with and whose worked days S3 minimizes. Both flags key off
    role, never off identity, so the model stays name-agnostic.
    """

    id: int
    display_name: str
    role: UserRole
    is_core: bool
    is_jolly: bool

    @property
    def compatible_roles(self) -> frozenset[AssignmentRole]:
        """The worked roles this worker may fill (H1/H2). Jolly is compatible
        with both bagnino and spiaggino; a core worker with exactly one."""
        if self.role is UserRole.JOLLY:
            return frozenset({AssignmentRole.BAGNINO, AssignmentRole.SPIAGGINO})
        if self.role is UserRole.BAGNINO:
            return frozenset({AssignmentRole.BAGNINO})
        return frozenset({AssignmentRole.SPIAGGINO})


@dataclass(frozen=True)
class PersonalConstraint:
    """A user-submitted unavailability (§6 constraints). `kind=HARD` becomes an
    H7 assumption literal so infeasibility can name it (§2.3); `kind=SOFT` becomes
    an S1 objective penalty (§2.2). `slot` may be day-level (`FULL_DAY`)."""

    worker_id: int
    day: Day
    slot: ConstraintSlot
    kind: ConstraintKind


@dataclass(frozen=True)
class Weights:
    """The lexicographic soft-objective weights (§2.2): W1 (S1 soft requests) >>
    {W2, W2_SPREAD} (S2 band) >> W3 (S3 Mattia clustering).

    The S2 band carries two coefficients: ``w2`` for alternation breaks + AM/PM
    fairness deviation, and ``w2_spread`` for the rest-spread term (full-weekend
    worker pairs sharing a free day). ``w2_spread`` sits above a single ``w2``
    alternation unit but far below ``w1`` (§2.2).

    Field carrier only — the actual constants and the separation arithmetic live
    in ``app.solver.weights``, not in this interface module.
    """

    w1: int
    w2: int
    w3: int
    w2_spread: int = 0


@dataclass(frozen=True)
class SolverInput:
    """Everything the pure solver reads for one week (§8). No DB handles."""

    # The week's Monday (Europe/Rome). Identifies the Mon–Fri days being solved.
    week_monday: dt.date
    # §1 roster, passed in — the solver never hardcodes names (see WorkerRef).
    roster: tuple[WorkerRef, ...]
    # H7/S1: user-submitted personal constraints, hard and soft mixed.
    constraints: tuple[PersonalConstraint, ...] = ()
    # Pinned free days: worker id → free day (Mon–Thu). Used by the golden test
    # and by the §2.3 sacrifice re-solve. A worker absent here has a
    # solver-chosen free day (H3 still forces exactly one).
    free_day_pins: Mapping[int, Day] = field(default_factory=dict)
    # S2 cross-week seed: worker id → last-worked boundary. Absent = no prior
    # state (legal first-ever week). See PriorSlot for the FULL_DAY case.
    prior_state: Mapping[int, PriorSlot] = field(default_factory=dict)
    # W1/W2/W2_SPREAD/W3 (§2.2). Defaulted to zero so callers must set real
    # weights; the model step owns the well-separated constants.
    weights: Weights = Weights(0, 0, 0, 0)


@dataclass(frozen=True)
class SlotAssignment:
    """One worked slot the solver assigned (§8 output). Mon–Fri only: `day` is
    never Sat/Sun. Mirrors a §6 `assignments` row minus provenance, which the
    adapter stamps as `source=solver` on persistence."""

    day: Day
    slot: AssignmentSlot
    role: AssignmentRole
    worker_id: int


@dataclass(frozen=True)
class ObjectiveBreakdown:
    """Per-tier objective values, present on a feasible solve. This is what the
    §8/§11 logging reads and what the tier-ordering tests assert against, so each
    tier is a separate named field (not a single blended score).

    `weighted_total == w1*soft_unmet + w2*(alternation_breaks + fairness_deviation)
    + w2_spread*spread_shared_pairs + w3*jolly_days`, with the input Weights — the
    same value CP-SAT minimizes.
    """

    soft_unmet: int  # S1 (W1): count of unmet soft personal requests.
    alternation_breaks: int  # S2 (W2): same-slot consecutive worked-day pairs.
    fairness_deviation: int  # S2 (W2): Σ over workers of |#AM − #PM| this week.
    # S2 (W2_SPREAD): count of full-weekend worker pairs sharing a free day.
    spread_shared_pairs: int
    jolly_days: int  # S3 (W3): count of days the jolly worker works ≥ 1 slot.
    weighted_total: int


@dataclass(frozen=True)
class SolverResult:
    """The solver's output (§8) plus diagnostics for logging and the sacrifice
    flow (§2.3)."""

    status: SolverStatus
    solve_seconds: float
    # Mon–Fri worked slots. Empty when status is INFEASIBLE.
    assignments: tuple[SlotAssignment, ...] = ()
    # Present on OPTIMAL/FEASIBLE; None on INFEASIBLE.
    objective: ObjectiveBreakdown | None = None
    # §2.3: on INFEASIBLE, the subset of input hard constraints that
    # `sufficient_assumptions_for_infeasibility()` named as blocking. Empty
    # otherwise. The API layer needs *which* constraint blocked, not just
    # INFEASIBLE.
    blocking_constraints: tuple[PersonalConstraint, ...] = ()


def solve(inp: SolverInput) -> SolverResult:
    """Solve one week's schedule (§8) — pure: no DB, no I/O, no global state.

    Builds the CP-SAT model (H1–H7 hard, S1–S3 soft), minimizes the
    well-separated W1/W2/W3 objective, and returns assignments with a per-tier
    breakdown, or — on INFEASIBLE — the blocking hard constraints named via
    assumption literals for the §2.3 sacrifice flow.

    The implementation lives in ``app.solver.model``; it is imported lazily so
    this interface module carries no CP-SAT dependency for pure type consumers.
    """
    from app.solver.model import solve as _solve

    return _solve(inp)
