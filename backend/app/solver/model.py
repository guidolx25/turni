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
    UserRole,
)
from app.solver.types import (
    SOLVER_DAYS,
    ObjectiveBreakdown,
    PersonalConstraint,
    PriorSlot,
    SlotAssignment,
    SolverInput,
    SolverResult,
    SolverStatus,
    WorkerRef,
    free_day_domain,
)

logger = logging.getLogger(__name__)

# §8/§11: a solve is trivial (< 1 s expected). Cap the search so it can never run
# away, and fail loudly past 10 s (see the wall-clock guard in solve()).
_MAX_SOLVE_SECONDS: float = 10.0

# Any fixed value works; what matters is that it never changes silently. The
# schedule this project publishes must be a function of its inputs alone.
_SOLVER_SEED: int = 20260713  # the golden week's Monday (§8), for traceability

_SLOTS: tuple[AssignmentSlot, ...] = (AssignmentSlot.AM, AssignmentSlot.PM)


def _single_role(worker: WorkerRef) -> AssignmentRole:
    """The lone worked role of a core worker (H4 works exactly one slot in it)."""
    (role,) = tuple(worker.compatible_roles)
    return role


def solve(inp: SolverInput) -> SolverResult:
    """Solve one week's Mon–Fri schedule (§8). Pure: no DB, no I/O.

    Builds the CP-SAT model (H1–H7 hard, S1–S2 soft), minimizes the
    well-separated W1/W2 objective (§2.2), and returns assignments with a
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

    # free[(uid, day)] — core workers only, over each worker's H3 domain D(u) (§8).
    # H3(b) + §2.3 sacrifice grant: D(u) is the worker's ROLE domain ({Mon, Tue} for
    # a spiaggino, {Tue, Wed} for a bagnino), widened to `role-domain ∪ {g}` for a
    # worker carrying a grant for day g. `free_day_domain` returns the role tuple
    # itself when no grant applies, so a normal solve's domains are exactly the role
    # domains by construction. Held per worker because the domains are NOT uniform
    # across the roster — they differ by role even before any grant — so every
    # downstream loop must use D(u); a loop over some fixed day tuple would silently
    # disagree with the variables that actually exist.
    domain: dict[int, tuple[object, ...]] = {}
    free: dict[tuple[int, object], cp_model.IntVar] = {}
    for w in roster:
        if w.is_core:
            domain[w.id] = free_day_domain(w.role, w.id, inp.sacrifice_grants)
            for d in domain[w.id]:
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

    # --- H3(a)/(b): exactly one free day within D(u); zero slots on it --------
    for w in roster:
        if not w.is_core:
            continue
        # H3(a) cardinality — UNCHANGED by a §2.3 grant: still exactly one free day.
        # The grant widens the set this sum ranges over, never the count (§2.1 H3).
        # H3(b) is encoded structurally: the sum ranges over D(u), so no free var
        # exists outside the role domain and the free day cannot land there.
        model.Add(sum(free[(w.id, d)] for d in domain[w.id]) == 1)
        # Pinned free day (§2.3 re-solve): it FORCES the free day onto that day,
        # within D(u). A pin outside D(u) has no variable to force and is ignored —
        # the §2.3 accept path always passes the matching grant alongside the pin
        # (that is what makes an out-of-domain pin legal), so this is a
        # belt-and-braces guard against a pin arriving without its grant.
        pin = inp.free_day_pins.get(w.id)
        if pin is not None and pin in domain[w.id]:
            model.Add(free[(w.id, pin)] == 1)
        for d in domain[w.id]:
            for s in _SLOTS:
                for r in w.compatible_roles:
                    # On the free day the worker works zero slots.
                    model.Add(x[(w.id, d, s, r)] <= 1 - free[(w.id, d)])

    # --- H3(c): two workers sharing a role never share a free day -------------
    # Explicitly encoded because it is NOT implied by H1/H6 coverage: a layout
    # resting both bagnini on Wednesday (or both spiaggini on Monday) covers fine
    # with the jolly doubling, so nothing else in the model rules it out. §2.1 H3(c)
    # excludes it deliberately, so that a role is never left to the jolly alone for
    # a whole day. This is the same behaviour the pre-v1.12 W2_SPREAD objective term
    # expressed — promoted from a soft preference over the full-weekend spiaggini to
    # a hard constraint over BOTH role pairs, so it hardened rather than lapsed.
    #
    # Pairing keys off `role`, never identity, and the day loop is D(u) ∩ D(v): a day
    # only one of them holds cannot be shared, so the intersection is this clause's
    # exact, total support. It stays correct under a §2.3 grant — a granted worker
    # still may not share with their same-role partner (§2.1 H3), and if the grant
    # widens D(u) into a day D(v) also holds, the intersection picks it up.
    core_by_role: dict[UserRole, list[int]] = {}
    for w in roster:
        if w.is_core:
            core_by_role.setdefault(w.role, []).append(w.id)
    for same_role_ids in core_by_role.values():
        ids = sorted(same_role_ids)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                u, v = ids[i], ids[j]
                for d in (d for d in domain[u] if d in domain[v]):
                    model.Add(free[(u, d)] + free[(v, d)] <= 1)

    # --- H4: exactly one slot per working weekday for core workers ------------
    for w in roster:
        if not w.is_core:
            continue
        r_u = _single_role(w)
        for d in SOLVER_DAYS:
            worked = sum(x[(w.id, d, s, r_u)] for s in _SLOTS)
            if d in domain[w.id]:
                # A day this worker may rest on: worked iff it is not their free day.
                model.Add(worked == 1 - free[(w.id, d)])
            else:
                # Outside D(u) there is no free var, so H4 forces the day worked.
                # This is what makes every day outside the role domain unrestable on
                # a normal solve — Thu and Fri for everyone, plus Wed for a spiaggino
                # and Mon for a bagnino — and what a §2.3 grant lifts for the granted
                # worker alone, on the one granted day (§2.3 reachable-days table).
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
            # H5 fixes Sat/Sun as a template, so a hard weekend request is not
            # droppable here without becoming silent (§2.3): it is escalated to
            # the admin at submission instead (`constraints._escalate_weekend_hard`).
            continue
        w = by_id[c.worker_id]
        lit = model.NewBoolVar(f"hard_{c.worker_id}_{c.day}_{c.slot}")
        for xv in _constrained_vars(x, w, c):
            # When the literal is assumed true, the worker cannot work the slot.
            model.Add(xv == 0).OnlyEnforceIf(lit)
        model.AddAssumption(lit)
        lit_to_constraint[lit.index] = c
        lit_by_index[lit.index] = lit

    # --- Objective S1–S2 (§2.2), well-separated weights (weights.py) ----------
    # Two tiers since v1.12. H3 now fixes free-day placement down to the 2×2
    # within-pair choice, and this objective is what resolves that choice (§8).
    w1, w2 = inp.weights.w1, inp.weights.w2

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

    # There is no third tier and no rest-spread term (v1.12). Rest spread is now
    # H3(c) above — hard, and over both role pairs — and the jolly's worked-day
    # count is no longer a degree of freedom: all four legal H3 layouts produce the
    # same jolly load (Mon 1 / Tue 2 / Wed 1 / Thu 0 / Fri 0), so a tier minimizing
    # it would be a no-op. Neither preference was dropped; both stopped being
    # *choices* the objective could influence.
    model.Minimize(w1 * soft_unmet + w2 * (alternation_breaks + fairness_deviation))

    # --- Solve -------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = _MAX_SOLVE_SECONDS
    # Deterministic search. CP-SAT's default portfolio runs several workers in
    # parallel and returns whichever optimum finishes first, so an equally
    # optimal schedule can differ between machines, runs and core counts. The
    # objective (§2.2) frequently admits ties — two workers' free days are often
    # interchangeable — which would make the §8 golden test a coin flip and any
    # reported schedule irreproducible when debugging. One worker plus a fixed
    # seed makes the same input yield the same week, everywhere, forever.
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = _SOLVER_SEED
    started = time.perf_counter()
    cp_status = solver.Solve(model)
    elapsed = time.perf_counter() - started

    # §8/§11: fail loudly past 10 s; anything over 1 s is a regression to probe.
    if elapsed > _MAX_SOLVE_SECONDS:
        raise RuntimeError(f"solver exceeded {_MAX_SOLVE_SECONDS:.0f}s wall clock ({elapsed:.2f}s)")

    if cp_status == cp_model.INFEASIBLE:
        # §2.3: CP-SAT returns *a* sufficient assumption set, not an irreducible
        # one — it can carry innocent literals that no minimal conflict needs.
        # Refine it down to ONE provably-minimal unsat core so attribution never
        # misdirects the "move your free day?" proposal to an innocent bystander.
        # Deterministic input order (sorted by literal index) → a stable core.
        sufficient = sorted(
            idx
            for idx in solver.SufficientAssumptionsForInfeasibility()
            if idx in lit_to_constraint
        )
        core = _minimal_unsat_core(model, solver, sufficient, lit_by_index)
        blocking = tuple(lit_to_constraint[idx] for idx in core)
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

    # §8/§11: every solve logs duration and the per-tier objective values.
    logger.info(
        "solver %s in %.3fs: soft_unmet=%d alternation_breaks=%d "
        "fairness_deviation=%d weighted_total=%d",
        solver.StatusName(cp_status),
        elapsed,
        breakdown.soft_unmet,
        breakdown.alternation_breaks,
        breakdown.fairness_deviation,
        breakdown.weighted_total,
    )

    status = SolverStatus.OPTIMAL if cp_status == cp_model.OPTIMAL else SolverStatus.FEASIBLE
    return SolverResult(
        status=status,
        solve_seconds=elapsed,
        assignments=assignments,
        objective=breakdown,
    )


def _minimal_unsat_core(
    model: cp_model.CpModel,
    solver: cp_model.CpSolver,
    sufficient: list[int],
    lit_by_index: dict[int, cp_model.IntVar],
) -> list[int]:
    """Shrink a sufficient assumption set to ONE provably-minimal unsat core (§2.3).

    ``SufficientAssumptionsForInfeasibility()`` proves infeasibility but is not
    irreducible: it can carry innocent literals that no minimal conflict needs.
    We minimize by deletion, walking ``sufficient`` in a FIXED, DETERMINISTIC
    order (it arrives sorted by literal index): for each assumption we drop it
    and re-solve with the remaining assumed. If the instance stays INFEASIBLE
    without it, it is a bystander and stays dropped; it survives ONLY if removal
    restores feasibility — i.e. it is critical. What remains is minimal by
    construction: every member is critical relative to the final set, so there
    are no bystanders, and unblocking the whole core restores feasibility.

    When the conflict is symmetric (e.g. either core bagnino blocked together
    with the jolly makes Monday uncoverable), this names ONE of the interchangeable
    minimal cores. The §2.3 flow then iterates per core: unblocking the named
    worker and re-solving surfaces the next core, so no responsible worker is
    lost — the loop resolves multi-conflict instances one core at a time.

    Attribution stays purely assumption-literal-driven (§8) — no heuristic about
    which constraints "look" blocking. Solves are trivial (§8), so this O(|S|)
    sweep of re-solves stays well under the 10 s guard.
    """

    def is_infeasible(indices: list[int]) -> bool:
        model.ClearAssumptions()
        model.AddAssumptions([lit_by_index[idx] for idx in indices])
        return solver.Solve(model) == cp_model.INFEASIBLE

    core = list(sufficient)
    for cand in sufficient:
        trial = [idx for idx in core if idx != cand]
        if is_infeasible(trial):
            core = trial  # `cand` is a bystander — the rest still conflict
        # else: dropping `cand` restored feasibility → it is critical, keep it.
    # Restore the full assumption set so the model is left as we found it (purity).
    model.ClearAssumptions()
    model.AddAssumptions(list(lit_by_index.values()))
    return core


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

    # No further tiers (v1.12): rest spread is H3(c), a hard constraint with no
    # objective value to report, and the jolly worked-day count is fixed by H3.
    w1, w2 = inp.weights.w1, inp.weights.w2
    weighted_total = w1 * soft_unmet + w2 * (alternation_breaks + fairness_deviation)
    return ObjectiveBreakdown(
        soft_unmet=soft_unmet,
        alternation_breaks=alternation_breaks,
        fairness_deviation=fairness_deviation,
        weighted_total=weighted_total,
    )
