"""The pure CP-SAT model behind ``solve(SolverInput) -> SolverResult`` (§8).

Mon–Fri only: the weekend is a fixed template (H5) and never a variable. The
function reads only its ``SolverInput`` dataclass and returns assignments plus
diagnostics — no DB access, no I/O beyond logging (§8: pure model).
"""

from __future__ import annotations

import logging
import time

from ortools.sat.python import cp_model

from app.enums import (
    AssignmentRole,
    AssignmentSlot,
    ConstraintKind,
    ConstraintSlot,
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
    WorkerRef,
)

logger = logging.getLogger(__name__)

# §8/§11: a solve is trivial (< 1 s expected). Cap the search so it can never run
# away, and fail loudly past 10 s (see the wall-clock guard in solve()).
_MAX_SOLVE_SECONDS: float = 10.0

_SLOTS: tuple[AssignmentSlot, ...] = (AssignmentSlot.AM, AssignmentSlot.PM)


def _single_role(worker: WorkerRef) -> AssignmentRole:
    """The lone worked role of a core worker (H4 works exactly one slot in it)."""
    (role,) = tuple(worker.compatible_roles)
    return role


def solve(inp: SolverInput) -> SolverResult:
    """Solve one week's Mon–Fri schedule (§8). Pure: no DB, no I/O.

    Builds the CP-SAT model (H1–H7 hard, S1–S3 soft), minimizes the
    well-separated W1/W2/W3 objective (§2.2), and returns assignments with a
    per-tier breakdown — or, on INFEASIBLE, the blocking hard constraints named
    via assumption literals for the §2.3 sacrifice flow.
    """
    model = cp_model.CpModel()
    roster = inp.roster
    by_id: dict[int, WorkerRef] = {w.id: w for w in roster}

    # --- Variables ---------------------------------------------------------
    # x[(uid, day, slot, role)] — restricted to role-compatible (u, r) pairs (§8).
    x: dict[tuple[int, object, AssignmentSlot, AssignmentRole], cp_model.IntVar] = {}
    for w in roster:
        for d in SOLVER_DAYS:
            for s in _SLOTS:
                for r in w.compatible_roles:
                    x[(w.id, d, s, r)] = model.NewBoolVar(f"x_{w.id}_{d}_{s}_{r}")

    # free[(uid, day)] — core workers only, Mon–Thu (H3).
    free: dict[tuple[int, object], cp_model.IntVar] = {}
    for w in roster:
        if w.is_core:
            for d in FREE_DAYS:
                free[(w.id, d)] = model.NewBoolVar(f"free_{w.id}_{d}")

    def works_slot(uid: int, d: object, s: AssignmentSlot) -> cp_model.LinearExpr:
        """1 iff worker ``uid`` works slot ``s`` on day ``d`` (H2 bounds it ≤ 1)."""
        w = by_id[uid]
        return sum(x[(uid, d, s, r)] for r in w.compatible_roles)

    # --- H1: coverage — exactly one bagnino and one spiaggino per slot --------
    for d in SOLVER_DAYS:
        for s in _SLOTS:
            for role in (AssignmentRole.BAGNINO, AssignmentRole.SPIAGGINO):
                model.Add(
                    sum(x[(w.id, d, s, role)] for w in roster if role in w.compatible_roles) == 1
                )

    # --- H2: one role per slot (only the jolly has two compatible roles) ------
    for w in roster:
        if len(w.compatible_roles) > 1:
            for d in SOLVER_DAYS:
                for s in _SLOTS:
                    model.Add(sum(x[(w.id, d, s, r)] for r in w.compatible_roles) <= 1)

    # --- H3: exactly one free day Mon–Thu; zero slots on it -------------------
    for w in roster:
        if not w.is_core:
            continue
        model.Add(sum(free[(w.id, d)] for d in FREE_DAYS) == 1)
        # Pinned free day (golden test / §2.3 re-solve). H3 forces the rest to 0.
        pin = inp.free_day_pins.get(w.id)
        if pin is not None and pin in FREE_DAYS:
            model.Add(free[(w.id, pin)] == 1)
        for d in FREE_DAYS:
            for s in _SLOTS:
                for r in w.compatible_roles:
                    # On the free day the worker works zero slots.
                    model.Add(x[(w.id, d, s, r)] <= 1 - free[(w.id, d)])

    # --- H4: exactly one slot per working weekday for core workers ------------
    for w in roster:
        if not w.is_core:
            continue
        r_u = _single_role(w)
        for d in SOLVER_DAYS:
            worked = sum(x[(w.id, d, s, r_u)] for s in _SLOTS)
            if d in FREE_DAYS:
                model.Add(worked == 1 - free[(w.id, d)])
            else:
                # Friday is never a free day (H3), so it is always worked.
                model.Add(worked == 1)

    # H5 is NOT modelled (weekend template, emitted elsewhere).
    # H6 is emergent: H1 coverage + role-compatibility force the jolly into the
    #    slots core free days leave open. No explicit constraint (§8/§2.1 H6).

    # --- H7: hard personal constraints as assumption literals (§2.3) ----------
    lit_to_constraint: dict[int, PersonalConstraint] = {}
    lit_by_index: dict[int, cp_model.IntVar] = {}
    for c in inp.constraints:
        if c.kind is not ConstraintKind.HARD:
            continue
        if c.day not in SOLVER_DAYS or c.worker_id not in by_id:
            # Weekend days / unknown workers have no Mon–Fri variables to block.
            continue
        w = by_id[c.worker_id]
        lit = model.NewBoolVar(f"hard_{c.worker_id}_{c.day}_{c.slot}")
        for xv in _constrained_vars(x, w, c):
            # When the literal is assumed true, the worker cannot work the slot.
            model.Add(xv == 0).OnlyEnforceIf(lit)
        model.AddAssumption(lit)
        lit_to_constraint[lit.index] = c
        lit_by_index[lit.index] = lit

    # --- Objective S1–S3 (§2.2), well-separated weights (weights.py) ----------
    w1, w2, w3 = inp.weights.w1, inp.weights.w2, inp.weights.w3

    # S1: one penalty per unmet SOFT request (worker works the constrained slot).
    soft_terms: list[cp_model.IntVar] = []
    for c in inp.constraints:
        if c.kind is not ConstraintKind.SOFT:
            continue
        if c.day not in SOLVER_DAYS or c.worker_id not in by_id:
            continue
        w = by_id[c.worker_id]
        viol = model.NewBoolVar(f"soft_{c.worker_id}_{c.day}_{c.slot}")
        for xv in _constrained_vars(x, w, c):
            model.Add(viol >= xv)  # viol = OR of the forbidden slots; min pulls it down.
        soft_terms.append(viol)
    soft_unmet = sum(soft_terms)

    # S2a: alternation breaks — same slot on two calendar-adjacent worked days.
    alt_terms: list[cp_model.LinearExpr] = []
    for w in roster:
        for d0, d1 in zip(SOLVER_DAYS, SOLVER_DAYS[1:], strict=False):
            for s in _SLOTS:
                b = model.NewBoolVar(f"alt_{w.id}_{d0}_{s}")
                # b = AND(works d0 s, works d1 s): min keeps it at max(0, sum-1).
                model.Add(b >= works_slot(w.id, d0, s) + works_slot(w.id, d1, s) - 1)
                alt_terms.append(b)
        # Cross-week Monday boundary (§2.2): prior slot seeds the alternation.
        prior = inp.prior_state.get(w.id)
        if prior is PriorSlot.AM:
            alt_terms.append(works_slot(w.id, SOLVER_DAYS[0], AssignmentSlot.AM))
        elif prior is PriorSlot.PM:
            alt_terms.append(works_slot(w.id, SOLVER_DAYS[0], AssignmentSlot.PM))
        elif prior is PriorSlot.FULL_DAY:
            # Both Sunday slots were worked -> whichever Monday slot collides.
            for s in _SLOTS:
                alt_terms.append(works_slot(w.id, SOLVER_DAYS[0], s))
    alternation_breaks = sum(alt_terms)

    # S2b: fairness — |#AM − #PM| per worker, linearized.
    fairness_terms: list[cp_model.IntVar] = []
    for w in roster:
        am = sum(works_slot(w.id, d, AssignmentSlot.AM) for d in SOLVER_DAYS)
        pm = sum(works_slot(w.id, d, AssignmentSlot.PM) for d in SOLVER_DAYS)
        dev = model.NewIntVar(0, len(SOLVER_DAYS), f"dev_{w.id}")
        model.Add(dev >= am - pm)
        model.Add(dev >= pm - am)
        fairness_terms.append(dev)
    fairness_deviation = sum(fairness_terms)

    # S3: jolly worked-day count (minimize -> induces free-day pairing).
    jolly_terms: list[cp_model.IntVar] = []
    jolly = next((w for w in roster if w.is_jolly), None)
    if jolly is not None:
        for d in SOLVER_DAYS:
            jw = model.NewBoolVar(f"jolly_works_{d}")
            for s in _SLOTS:
                model.Add(jw >= works_slot(jolly.id, d, s))
            jolly_terms.append(jw)
    jolly_days = sum(jolly_terms)

    model.Minimize(
        w1 * soft_unmet + w2 * (alternation_breaks + fairness_deviation) + w3 * jolly_days
    )

    # --- Solve -------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = _MAX_SOLVE_SECONDS
    started = time.perf_counter()
    cp_status = solver.Solve(model)
    elapsed = time.perf_counter() - started

    # §8/§11: fail loudly past 10 s; anything over 1 s is a regression to probe.
    if elapsed > _MAX_SOLVE_SECONDS:
        raise RuntimeError(f"solver exceeded {_MAX_SOLVE_SECONDS:.0f}s wall clock ({elapsed:.2f}s)")

    if cp_status == cp_model.INFEASIBLE:
        # §2.3: CP-SAT returns *a* sufficient assumption set, not an irreducible
        # one — it can carry innocent literals that no minimal conflict needs.
        # Refine it to exactly the hard constraints that actually participate in
        # the conflict so attribution never misdirects the "move your free day?"
        # proposal to an innocent bystander.
        sufficient = [
            idx
            for idx in solver.SufficientAssumptionsForInfeasibility()
            if idx in lit_to_constraint
        ]
        culprits = _conflicting_hard_constraints(model, solver, sufficient, lit_by_index)
        blocking = tuple(lit_to_constraint[idx] for idx in culprits)
        # The extra re-solves are trivial (§8), but they still count against the
        # §8/§11 wall-clock budget — re-measure and keep the loud 10 s guard.
        elapsed = time.perf_counter() - started
        if elapsed > _MAX_SOLVE_SECONDS:
            raise RuntimeError(
                f"solver exceeded {_MAX_SOLVE_SECONDS:.0f}s wall clock ({elapsed:.2f}s)"
            )
        logger.info(
            "solver INFEASIBLE in %.3fs; sufficient=%d blocking_constraints=%d",
            elapsed,
            len(sufficient),
            len(blocking),
        )
        return SolverResult(
            status=SolverStatus.INFEASIBLE,
            solve_seconds=elapsed,
            blocking_constraints=blocking,
        )

    if cp_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # UNKNOWN / MODEL_INVALID on a trivial problem is never expected (§8).
        raise RuntimeError(f"unexpected CP-SAT status {solver.StatusName(cp_status)}")

    assignments = _extract_assignments(solver, x, roster)
    breakdown = _breakdown(assignments, inp)

    logger.info(
        "solver %s in %.3fs: soft_unmet=%d alternation_breaks=%d "
        "fairness_deviation=%d jolly_days=%d weighted_total=%d",
        solver.StatusName(cp_status),
        elapsed,
        breakdown.soft_unmet,
        breakdown.alternation_breaks,
        breakdown.fairness_deviation,
        breakdown.jolly_days,
        breakdown.weighted_total,
    )

    status = SolverStatus.OPTIMAL if cp_status == cp_model.OPTIMAL else SolverStatus.FEASIBLE
    return SolverResult(
        status=status,
        solve_seconds=elapsed,
        assignments=assignments,
        objective=breakdown,
    )


def _conflicting_hard_constraints(
    model: cp_model.CpModel,
    solver: cp_model.CpSolver,
    sufficient: list[int],
    lit_by_index: dict[int, cp_model.IntVar],
) -> list[int]:
    """Refine a sufficient assumption set into the hard constraints that actually
    participate in the conflict — the UNION of its minimal unsat cores (§2.3).

    ``SufficientAssumptionsForInfeasibility()`` proves infeasibility but is not
    irreducible: it can include innocent literals that no minimal conflict needs.
    A single deletion-filtered minimal core is *also* insufficient for §2.3: when
    the conflict is symmetric — e.g. either core bagnino blocked *together with*
    the jolly makes Monday uncoverable — a lone core names only one of two
    interchangeable culprits and the sacrifice flow would silently ignore the
    other responsible worker. So we keep a literal iff it is load-bearing in
    *some* minimal core, dropping only pure bystanders (necessary for no
    conflict). Attribution stays purely assumption-literal-driven (§8) — no
    heuristic about which constraints "look" blocking. Solves are trivial (§8),
    so this O(|S|^2) sweep of re-solves stays well under the 10 s guard.
    """

    def is_infeasible(indices: list[int]) -> bool:
        model.ClearAssumptions()
        model.AddAssumptions([lit_by_index[idx] for idx in indices])
        return solver.Solve(model) == cp_model.INFEASIBLE

    culprits: list[int] = []
    for pinned in sufficient:
        # Shrink `sufficient` toward a minimal conflict while never dropping
        # `pinned`; `pinned` lies in some minimal core iff it is then critical.
        core = list(sufficient)
        for cand in sufficient:
            if cand == pinned:
                continue
            trial = [idx for idx in core if idx != cand]
            if is_infeasible(trial):
                core = trial  # `cand` not needed here; the rest still conflict
        if not is_infeasible([idx for idx in core if idx != pinned]):
            culprits.append(pinned)  # removing `pinned` breaks the conflict
    # Restore the full assumption set so the model is left as we found it (purity).
    model.ClearAssumptions()
    model.AddAssumptions(list(lit_by_index.values()))
    return culprits


def _constrained_vars(
    x: dict[tuple[int, object, AssignmentSlot, AssignmentRole], cp_model.IntVar],
    worker: WorkerRef,
    c: PersonalConstraint,
) -> list[cp_model.IntVar]:
    """The x-vars a personal constraint forbids: one slot (AM/PM) or the whole
    day (FULL_DAY), across every role the worker can fill (H7 / S1)."""
    slots = _SLOTS if c.slot is ConstraintSlot.FULL_DAY else (AssignmentSlot(c.slot.value),)
    return [
        x[(worker.id, c.day, s, r)]
        for s in slots
        for r in worker.compatible_roles
        if (worker.id, c.day, s, r) in x
    ]


def _extract_assignments(
    solver: cp_model.CpSolver,
    x: dict[tuple[int, object, AssignmentSlot, AssignmentRole], cp_model.IntVar],
    roster: tuple[WorkerRef, ...],
) -> tuple[SlotAssignment, ...]:
    """Read the solved worked slots into §8 output rows (Mon–Fri only)."""
    rows: list[SlotAssignment] = []
    for (uid, d, s, r), var in x.items():
        if solver.Value(var):
            rows.append(SlotAssignment(day=d, slot=s, role=r, worker_id=uid))
    rows.sort(key=lambda a: (SOLVER_DAYS.index(a.day), a.slot.value, a.role.value))
    return tuple(rows)


def _breakdown(assignments: tuple[SlotAssignment, ...], inp: SolverInput) -> ObjectiveBreakdown:
    """Recompute the per-tier objective values from the final assignments so the
    reported breakdown is provably the value CP-SAT minimized (§8 logging)."""
    worked: set[tuple[int, object, AssignmentSlot]] = {
        (a.worker_id, a.day, a.slot) for a in assignments
    }

    def works(uid: int, d: object, s: AssignmentSlot) -> bool:
        return (uid, d, s) in worked

    # S1: unmet soft requests.
    soft_unmet = 0
    for c in inp.constraints:
        if c.kind is not ConstraintKind.SOFT or c.day not in SOLVER_DAYS:
            continue
        slots = _SLOTS if c.slot is ConstraintSlot.FULL_DAY else (AssignmentSlot(c.slot.value),)
        if any(works(c.worker_id, c.day, s) for s in slots):
            soft_unmet += 1

    # S2a: alternation breaks (internal adjacencies + Monday boundary).
    alternation_breaks = 0
    for w in inp.roster:
        for d0, d1 in zip(SOLVER_DAYS, SOLVER_DAYS[1:], strict=False):
            for s in _SLOTS:
                if works(w.id, d0, s) and works(w.id, d1, s):
                    alternation_breaks += 1
        prior = inp.prior_state.get(w.id)
        mon = SOLVER_DAYS[0]
        if (prior is PriorSlot.AM and works(w.id, mon, AssignmentSlot.AM)) or (
            prior is PriorSlot.PM and works(w.id, mon, AssignmentSlot.PM)
        ):
            alternation_breaks += 1
        elif prior is PriorSlot.FULL_DAY:
            alternation_breaks += sum(works(w.id, mon, s) for s in _SLOTS)

    # S2b: fairness deviation.
    fairness_deviation = 0
    for w in inp.roster:
        am = sum(works(w.id, d, AssignmentSlot.AM) for d in SOLVER_DAYS)
        pm = sum(works(w.id, d, AssignmentSlot.PM) for d in SOLVER_DAYS)
        fairness_deviation += abs(am - pm)

    # S3: jolly worked-day count.
    jolly_days = 0
    jolly = next((w for w in inp.roster if w.is_jolly), None)
    if jolly is not None:
        jolly_days = sum(1 for d in SOLVER_DAYS if any(works(jolly.id, d, s) for s in _SLOTS))

    w1, w2, w3 = inp.weights.w1, inp.weights.w2, inp.weights.w3
    weighted_total = (
        w1 * soft_unmet + w2 * (alternation_breaks + fairness_deviation) + w3 * jolly_days
    )
    return ObjectiveBreakdown(
        soft_unmet=soft_unmet,
        alternation_breaks=alternation_breaks,
        fairness_deviation=fairness_deviation,
        jolly_days=jolly_days,
        weighted_total=weighted_total,
    )
