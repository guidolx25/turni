"""Shared, deterministic fixtures and query helpers for the solver suite (§8).

The §1 roster is expressed as `WorkerRef` tuples with STABLE ids so this suite
and the parallel model smoke-tests agree on identity:

    1=Matteo (bagnino, core)   2=Francesco (bagnino, core)
    3=Pasha  (spiaggino, core) 4=Amir      (spiaggino, core)
    5=Mattia (jolly)

Everything here is pure data plus small readers over `SlotAssignment` tuples —
no DB, no I/O. Tests assert STRUCTURAL properties that hold across any optimal
solution (coverage, free-day counts, objective breakdown), never a single
AM/PM tie-break, because CP-SAT is free to choose among equal-cost layouts.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from app.enums import AssignmentRole, AssignmentSlot, Day, UserRole
from app.solver.types import (
    SOLVER_DAYS,
    PriorSlot,
    SlotAssignment,
    Weights,
    WorkerRef,
)
from app.solver.weights import DEFAULT_WEIGHTS

# Stable roster ids (§1). Named so tests read as the spec does.
MATTEO = 1
FRANCESCO = 2
PASHA = 3
AMIR = 4
MATTIA = 5

CORE_IDS: frozenset[int] = frozenset({MATTEO, FRANCESCO, PASHA, AMIR})
BAGNINO_CORE_IDS: frozenset[int] = frozenset({MATTEO, FRANCESCO})
SPIAGGINO_CORE_IDS: frozenset[int] = frozenset({PASHA, AMIR})

# The photographed golden week (§8; CLAUDE reproduces 2026-07-13). A Monday.
WEEK_MONDAY: dt.date = dt.date(2026, 7, 13)

# Production weights (§2.2) — imported, never hardcoded, so the tier-ordering
# tests track the real, well-separated W1 >> W2 >> W3 constants.
WEIGHTS: Weights = DEFAULT_WEIGHTS


def roster() -> tuple[WorkerRef, ...]:
    """The §1 roster as the solver sees it (stable ids, role-derived flags)."""
    return (
        WorkerRef(MATTEO, "Matteo", UserRole.BAGNINO, is_core=True, is_jolly=False),
        WorkerRef(FRANCESCO, "Francesco", UserRole.BAGNINO, is_core=True, is_jolly=False),
        WorkerRef(PASHA, "Pasha", UserRole.SPIAGGINO, is_core=True, is_jolly=False),
        WorkerRef(AMIR, "Amir", UserRole.SPIAGGINO, is_core=True, is_jolly=False),
        WorkerRef(MATTIA, "Mattia", UserRole.JOLLY, is_core=False, is_jolly=True),
    )


def canonical_prior_state() -> dict[int, PriorSlot]:
    """The §2.2 weekend seed for the Monday boundary.

    Matteo exits Sunday PM, Francesco Sunday AM, Pasha and Amir full-day.
    Mattia never works the weekend (§H5), so he is absent → no boundary term.
    """
    return {
        MATTEO: PriorSlot.PM,
        FRANCESCO: PriorSlot.AM,
        PASHA: PriorSlot.FULL_DAY,
        AMIR: PriorSlot.FULL_DAY,
    }


# --- readers over a solved assignment tuple ---------------------------------


def slots_by_role(
    assignments: tuple[SlotAssignment, ...],
) -> dict[tuple[Day, AssignmentSlot, AssignmentRole], list[int]]:
    """(day, slot, role) → worker ids assigned to it (H1 coverage view)."""
    out: dict[tuple[Day, AssignmentSlot, AssignmentRole], list[int]] = defaultdict(list)
    for a in assignments:
        out[(a.day, a.slot, a.role)].append(a.worker_id)
    return out


def workers_in_slot(
    assignments: tuple[SlotAssignment, ...],
) -> dict[tuple[Day, AssignmentSlot], list[int]]:
    """(day, slot) → worker ids present (H2: a worker holds ≤ 1 role per slot)."""
    out: dict[tuple[Day, AssignmentSlot], list[int]] = defaultdict(list)
    for a in assignments:
        out[(a.day, a.slot)].append(a.worker_id)
    return out


def worker_days(
    assignments: tuple[SlotAssignment, ...], worker_id: int
) -> dict[Day, list[SlotAssignment]]:
    """day → this worker's assignments that day (H3/H4 free-day + load view)."""
    out: dict[Day, list[SlotAssignment]] = defaultdict(list)
    for a in assignments:
        if a.worker_id == worker_id:
            out[a.day].append(a)
    return out


def free_day_of(assignments: tuple[SlotAssignment, ...], worker_id: int) -> Day | None:
    """The single Mon–Thu day this core worker worked zero slots (H3), or None
    if they worked every solver day (which would violate H3)."""
    worked = {a.day for a in assignments if a.worker_id == worker_id}
    free = [d for d in SOLVER_DAYS if d not in worked]
    if len(free) != 1:
        return None
    return free[0]


def assignments_of(assignments: tuple[SlotAssignment, ...], worker_id: int) -> list[SlotAssignment]:
    """All slots this worker was assigned, across the week."""
    return [a for a in assignments if a.worker_id == worker_id]
