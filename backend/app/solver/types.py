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

# H3(b): a core worker's DEFAULT free-day domain is determined by their ROLE, never
# by identity (§2.1 H3(b), v1.12). Thursday and Friday are outside every default
# domain — no core worker rests on either without a §2.3 grant. The jolly is not a
# core worker and has no free day at all, hence no entry here.
ROLE_FREE_DAYS: Mapping[UserRole, tuple[Day, ...]] = {
    UserRole.SPIAGGINO: (Day.MON, Day.TUE),
    UserRole.BAGNINO: (Day.TUE, Day.WED),
}


def free_day_domain(role: UserRole, worker_id: int, grants: Mapping[int, Day]) -> tuple[Day, ...]:
    """H3(b) + §2.3 sacrifice grant: the days worker ``worker_id`` may take free.

    The worker's **role domain** by default — ``{Mon, Tue}`` for a spiaggino,
    ``{Tue, Wed}`` for a bagnino (§2.1 H3(b)) — and ``role-domain ∪ {g}`` for a
    worker holding a grant for day ``g``. H3(a)'s *cardinality* (exactly one free
    day) and H3(c)'s *distinctness* are untouched by a grant; only *where* the free
    day may fall widens.

    The domain is keyed off ``role``, never off ``worker_id``: the id selects only
    which grant applies. This is the single place the domain is computed, so "a
    normal solve's domains are exactly the role domains" holds **by construction**
    — with no grant the function returns the ``ROLE_FREE_DAYS`` tuple itself.

    Two kinds of grant are deliberately not extendable (§2.3 reachable-days table):

    - A grant for a day already in the role domain is a no-op (nothing to widen),
      so the probe reduces to the plain solve plus a pin. A pin only ADDS
      ``free[u][d] = 1``, so that probe's feasible region is a subset and an
      INFEASIBLE week stays INFEASIBLE — for slot-level and full-day requests
      alike. Such a conflict escalates rather than producing a proposal.
    - A grant for Sat/Sun is REFUSED. H5 makes the weekend a fixed template with
      no solver variables, so a weekend free var would satisfy H3's cardinality
      without freeing any weekday — the worker would work all five weekdays and
      H3 would be silently void. Weekend hard requests escalate instead (§2.3).

    What remains reachable therefore differs by role — Wed/Thu/Fri for a spiaggino,
    Mon/Thu/Fri for a bagnino — as a *consequence* of these rules rather than as a
    special case written into them.
    """
    base = ROLE_FREE_DAYS.get(role, ())
    grant = grants.get(worker_id)
    if grant is None or grant in base or grant not in SOLVER_DAYS:
        return base
    return (*base, grant)


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
    fills open slots with. Both flags key off role, never off identity, so the
    model stays name-agnostic — as does `role` itself, which selects the H3(b)
    free-day domain (`free_day_domain`) and the H3(c) same-role pairing.
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
    W2 (S2 alternation breaks + AM/PM fairness deviation).

    Two tiers, and only two (v1.12). The former ``w2_spread`` coefficient is gone
    because the rest-spread *behaviour* was PROMOTED into H3(c), where it is a hard
    constraint covering both role pairs rather than a soft term covering only the
    full-weekend spiaggini — the preference did not weaken, it hardened. The former
    ``w3`` is gone because H3 now fixes free-day placement outright, leaving the
    Mattia-clustering tier with nothing to optimize.

    Field carrier only — the actual constants and the separation arithmetic live
    in ``app.solver.weights``, not in this interface module.
    """

    w1: int
    w2: int


@dataclass(frozen=True)
class SolverInput:
    """Everything the pure solver reads for one week (§8). No DB handles."""

    # The week's Monday (Europe/Rome). Identifies the Mon–Fri days being solved.
    week_monday: dt.date
    # §1 roster, passed in — the solver never hardcodes names (see WorkerRef).
    roster: tuple[WorkerRef, ...]
    # H7/S1: user-submitted personal constraints, hard and soft mixed.
    constraints: tuple[PersonalConstraint, ...] = ()
    # Pinned free days: worker id → free day. Used by the §2.3 sacrifice re-solve.
    # A worker absent here has a solver-chosen free day (H3 still forces exactly
    # one). A pin outside the worker's H3 domain has no variable to force and is
    # ignored. NOT used by the §8 golden test, which since v1.12 reproduces the
    # photographed week UNPINNED — H3(b)+(c) derive the role-day structure.
    free_day_pins: Mapping[int, Day] = field(default_factory=dict)
    # H3 + §2.3 sacrifice grant: worker id → the day their free-day domain is
    # extended to (`role-domain ∪ {day}`). EXPLICIT and first-class, deliberately
    # distinct from `free_day_pins`: a pin only *forces* a free day the domain
    # already allows, a grant *widens* the domain. A pin alone can never rescue an
    # infeasible week — it only adds `free[u][d] = 1`, shrinking the feasible
    # region — so the grant is what makes the §2.3 propose branch reachable at all.
    # EMPTY on every normal solve, where all domains are exactly the role domains; issued
    # only by the §2.3 flow, only for the day named in the blocking hard request,
    # only for that week. It never touches H7: the hard request is still honored
    # in full (§2.3 "What is being traded" — the trade is free-day PLACEMENT).
    sacrifice_grants: Mapping[int, Day] = field(default_factory=dict)
    # S2 cross-week seed: worker id → last-worked boundary. Absent = no prior
    # state (legal first-ever week). See PriorSlot for the FULL_DAY case.
    prior_state: Mapping[int, PriorSlot] = field(default_factory=dict)
    # (v1.12 carries no full-weekend id set. It existed only to seed the rest-spread
    # objective term with the two full-day spiaggini; that behaviour is now H3(c),
    # a hard constraint keyed off `role`, which every WorkerRef already carries, so
    # the solver derives the same structure from the roster it is already given.)
    # W1/W2 (§2.2). Defaulted to zero so callers must set real weights; the model
    # step owns the well-separated constants.
    weights: Weights = Weights(0, 0)


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

    `weighted_total == w1*soft_unmet + w2*(alternation_breaks + fairness_deviation)`,
    with the input Weights — the same value CP-SAT minimizes.

    Two tiers since v1.12: the rest-spread count is no longer an objective value to
    report because H3(c) makes a shared same-role free day *impossible* rather than
    merely expensive, and the jolly worked-day count is no longer an objective value
    because H3 fixes it (Mon 1 / Tue 2 / Wed 1 / Thu 0 / Fri 0 on every legal layout).
    """

    soft_unmet: int  # S1 (W1): count of unmet soft personal requests.
    alternation_breaks: int  # S2 (W2): same-slot consecutive worked-day pairs.
    fairness_deviation: int  # S2 (W2): Σ over workers of |#AM − #PM| this week.
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

    Builds the CP-SAT model (H1–H7 hard, S1–S2 soft), minimizes the
    well-separated W1/W2 objective, and returns assignments with a per-tier
    breakdown, or — on INFEASIBLE — the blocking hard constraints named via
    assumption literals for the §2.3 sacrifice flow.

    The implementation lives in ``app.solver.model``; it is imported lazily so
    this interface module carries no CP-SAT dependency for pure type consumers.
    """
    from app.solver.model import solve as _solve

    return _solve(inp)
