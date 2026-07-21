"""Role compatibility — who may hold which assignment row (spec §1, §4, §5).

One rule, one implementation. §4 states it for swaps ("bagnino↔bagnino,
spiaggino↔spiaggino. Mattia matches either role") and §5's admin override moves
the same rows, so both instruments must agree on what a legal holder is. A second
copy would eventually drift, and the direction it drifts in is an override that
seats a spiaggino in a bagnino slot — a coverage rule (H1) broken by a typo
rather than by a decision.

Keyed on the worker's ROLE, never on identity (§1: the jolly is defined by
`role=jolly`, not by being Mattia).
"""

from __future__ import annotations

from app.enums import AssignmentRole, UserRole


def can_hold(user_role: UserRole, row_role: AssignmentRole) -> bool:
    """§1/§4: may a worker with `user_role` hold an assignment row of `row_role`?

    The jolly holds either role (§1, H6); everyone else holds only their own.
    """
    if user_role is UserRole.JOLLY:
        return True
    return user_role.value == row_role.value
