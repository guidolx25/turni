"""API request/response models (spec §7).

`is_root` is *structurally absent* from every user schema — not excluded by a
conditional, not hidden by an `exclude=` at a call site. §5 makes root's
invisibility a property of the system, and a field that does not exist cannot be
leaked by a branch someone forgets to write. Root-ness reaches the wire only as
the 403 a non-root gets from a root-only route.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.enums import (
    AssignmentRole,
    AssignmentSlot,
    AssignmentSource,
    ConstraintKind,
    ConstraintSlot,
    Day,
    Language,
    SacrificeStatus,
    UserRole,
    WeekStatus,
)
from app.models import Assignment, Constraint, SacrificeProposal, User, Week
from app.permissions import has_admin_capability, has_root_capability
from app.scheduling import window_deadline
from app.solver import PersonalConstraint, SolverResult


class LoginIn(BaseModel):
    """`POST /auth/login` body."""

    # Bounded to keep an absurd body from reaching argon2 (which will happily
    # hash megabytes) or from filling a rate-limit key.
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    """A user as any authenticated caller may see them (§5).

    `is_admin` is here on purpose: §5 makes the admin visible. `is_root` is not,
    and must never be added.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: UserRole
    is_admin: bool
    email: str | None
    email_notifications: bool
    language: Language
    active: bool


class UserAdminOut(UserOut):
    """A user as root may see them (`GET /root/users`, §7).

    Adds only administrative metadata; it inherits UserOut's fields and so
    inherits the absence of `is_root` too. §7 confines the capability booleans to
    /me, so they are absent here as well: this endpoint answers "who exists", not
    "what may they do".
    """

    created_at: dt.datetime


class Capabilities(BaseModel):
    """The caller's own §5 matrix rows, as derived booleans (§7).

    One field per capability row, named for the row rather than for the flag
    behind it: the frontend gates on "may I override a locked slot", not on "am I
    an admin". If §5 ever moves a row between tiers, the wiring in `for_user`
    changes and every consumer follows — no field renames, no frontend edit.

    The two unconditional rows ("submit/edit own constraints", "view schedule,
    request/accept swaps") are deliberately NOT emitted: every caller who can
    reach /me is authenticated and active, so those rows are true for all of
    them. A boolean that is never false is not a signal, and shipping one invites
    the frontend to branch on a condition that cannot occur.
    """

    # §5 rows 3-6 — admin tier (root inherits).
    trigger_solve: bool
    override_locked_slots: bool
    view_all_constraints: bool
    view_audit_log: bool
    # §5 rows 7-8 — root tier.
    manage_users: bool
    see_root_account: bool

    @classmethod
    def for_user(cls, user: User) -> Capabilities:
        """Derive the caller's capabilities from `app.permissions`.

        These predicates are the *same functions* the permission dependencies
        enforce with (`app.deps`); this method only maps matrix rows onto them.
        Never re-derive a row from `user.is_admin` / `user.is_root` here — a
        second reading of the flags is a second matrix, and the two would drift
        until the UI offered a button the API refuses.
        """
        admin = has_admin_capability(user)
        root = has_root_capability(user)
        return cls(
            trigger_solve=admin,
            override_locked_slots=admin,
            view_all_constraints=admin,
            view_audit_log=admin,
            manage_users=root,
            see_root_account=root,
        )


class MeOut(UserOut):
    """`GET /me` (§7): the caller's own account, plus their own capabilities.

    Its own schema because UserOut is the shape used for *other* users, and §7
    puts the capability booleans on /me only. Inheriting UserOut inherits the
    absence of `is_root`: `capabilities.see_root_account` is what root learns
    about itself, which is a statement about the caller's authority, not the flag
    itself resurfacing.
    """

    capabilities: Capabilities

    @classmethod
    def for_user(cls, user: User) -> MeOut:
        """Build from the ORM row.

        Explicit rather than `from_attributes`: capabilities are derived (§7) and
        have no column to read.
        """
        return cls(
            **UserOut.model_validate(user).model_dump(),
            capabilities=Capabilities.for_user(user),
        )


class WeekOut(BaseModel):
    """A week's lifecycle state (§7 `GET /weeks`): its Monday, status, the derived
    Sunday-17:00 submission deadline, and the solve/lock timestamps.

    `submission_deadline` is *computed* (`app.scheduling.window_deadline`), not a
    stored column — the frontend renders a countdown from it, so it must be the
    same instant the lifecycle enforces, never a second copy.
    """

    monday_date: dt.date
    status: WeekStatus
    submission_deadline: dt.datetime
    solved_at: dt.datetime | None
    locked_at: dt.datetime | None

    @classmethod
    def from_week(cls, week: Week) -> WeekOut:
        return cls(
            monday_date=week.monday_date,
            status=week.status,
            submission_deadline=window_deadline(week.monday_date),
            solved_at=week.solved_at,
            locked_at=week.locked_at,
        )


class ConstraintIn(BaseModel):
    """`POST /constraints` body (§7). The week is named by its Monday date — the
    §6 natural key — not a surrogate id, so clients never depend on a lazily
    created week row's id."""

    week: dt.date
    day: Day
    slot: ConstraintSlot
    kind: ConstraintKind
    # §6 `constraints.note` is free text; bounded so a submission cannot smuggle a
    # huge payload past the JSON column.
    note: str | None = Field(default=None, max_length=500)


class ConstraintOut(BaseModel):
    """One of the caller's own constraints (§7 `GET /constraints`). Echoes the
    week by its Monday date to mirror `ConstraintIn`, so a round-trip is stable."""

    id: int
    week: dt.date
    day: Day
    slot: ConstraintSlot
    kind: ConstraintKind
    note: str | None
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def from_model(cls, constraint: Constraint) -> ConstraintOut:
        return cls(
            id=constraint.id,
            week=constraint.week.monday_date,
            day=constraint.day,
            slot=constraint.slot,
            kind=constraint.kind,
            note=constraint.note,
            created_at=constraint.created_at,
            updated_at=constraint.updated_at,
        )


class ScheduleAssignmentOut(BaseModel):
    """One worked slot in a published schedule (§7 `GET /schedule`).

    Carries the worker's `display_name` so the grid needs no second lookup, but
    never `is_root`: root (Matteo) appears here as an ordinary bagnino — his shifts
    are real coverage — while his root role stays invisible (§5)."""

    day: Day
    slot: AssignmentSlot
    role: AssignmentRole
    user_id: int
    user_name: str
    source: AssignmentSource

    @classmethod
    def from_model(cls, assignment: Assignment) -> ScheduleAssignmentOut:
        return cls(
            day=assignment.day,
            slot=assignment.slot,
            role=assignment.role,
            user_id=assignment.user_id,
            user_name=assignment.user.display_name,
            source=assignment.source,
        )


class ScheduleOut(BaseModel):
    """A week's schedule (§7 `GET /schedule`): its lifecycle state plus every
    worked slot, weekday (solver) and weekend (template) alike."""

    monday_date: dt.date
    status: WeekStatus
    assignments: list[ScheduleAssignmentOut]


class SacrificeProposalOut(BaseModel):
    """A §2.3 sacrifice proposal as its target worker sees it (accept/decline).
    Echoes the week by Monday date and the offered free day."""

    id: int
    week: dt.date
    proposed_free_day: Day
    status: SacrificeStatus
    conflict_note: str | None
    created_at: dt.datetime

    @classmethod
    def from_model(cls, proposal: SacrificeProposal) -> SacrificeProposalOut:
        return cls(
            id=proposal.id,
            week=proposal.week.monday_date,
            proposed_free_day=proposal.proposed_free_day,
            status=proposal.status,
            conflict_note=proposal.conflict_note,
            created_at=proposal.created_at,
        )


class NotificationOut(BaseModel):
    """One of the caller's own in-app notifications (§7 `GET /notifications`,
    §10 Channel 1)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    payload: dict[str, object] | None
    read: bool
    created_at: dt.datetime


class MarkReadIn(BaseModel):
    """`POST /notifications/read` body (§7). `ids` omitted marks all the caller's
    notifications read; a list marks exactly those (own rows only)."""

    ids: list[int] | None = None


class BlockingConstraintOut(BaseModel):
    """A hard constraint named as blocking on an INFEASIBLE solve (§2.3). Feeds the
    sacrifice-flow proposal, so it echoes exactly which (worker, day, slot) conflicts."""

    worker_id: int
    day: Day
    slot: ConstraintSlot
    kind: ConstraintKind

    @classmethod
    def from_constraint(cls, c: PersonalConstraint) -> BlockingConstraintOut:
        return cls(worker_id=c.worker_id, day=c.day, slot=c.slot, kind=c.kind)


class ObjectiveBreakdownOut(BaseModel):
    """Per-tier objective values on a feasible solve (§8 logging / admin view)."""

    soft_unmet: int
    alternation_breaks: int
    fairness_deviation: int
    spread_shared_pairs: int
    jolly_days: int
    weighted_total: int


class SolveResultOut(BaseModel):
    """`POST /admin/solve` outcome (§7). Feasible carries the objective breakdown;
    INFEASIBLE carries the blocking constraints for the §2.3 sacrifice flow."""

    status: str
    solve_seconds: float
    objective: ObjectiveBreakdownOut | None
    blocking_constraints: list[BlockingConstraintOut]

    @classmethod
    def from_result(cls, result: SolverResult) -> SolveResultOut:
        objective = None
        if result.objective is not None:
            objective = ObjectiveBreakdownOut(
                soft_unmet=result.objective.soft_unmet,
                alternation_breaks=result.objective.alternation_breaks,
                fairness_deviation=result.objective.fairness_deviation,
                spread_shared_pairs=result.objective.spread_shared_pairs,
                jolly_days=result.objective.jolly_days,
                weighted_total=result.objective.weighted_total,
            )
        return cls(
            status=result.status.value,
            solve_seconds=result.solve_seconds,
            objective=objective,
            blocking_constraints=[
                BlockingConstraintOut.from_constraint(c) for c in result.blocking_constraints
            ],
        )
