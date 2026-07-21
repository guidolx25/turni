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
    SwapStatus,
    UserRole,
    WeekStatus,
)
from app.models import (
    Assignment,
    AuditLog,
    Constraint,
    SacrificeProposal,
    SwapRequest,
    User,
    Week,
)
from app.permissions import has_admin_capability, has_root_capability
from app.scheduling import window_deadline
from app.solver import PersonalConstraint, SolverResult


class LoginIn(BaseModel):
    """`POST /auth/login` body."""

    # Bounded to keep an absurd body from reaching argon2 (which will happily
    # hash megabytes) or from filling a rate-limit key.
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class MeSettingsIn(BaseModel):
    """`PATCH /me/settings` body (§7: language, email_notifications, password change).

    Every field is optional and a partial patch: absent means "leave alone".

    §7 confines this endpoint to the user's *own preferences*. `role`, `is_admin`,
    `is_root`, `active` and `ics_token` are structurally absent — privilege
    escalation by PATCH is not something to defend against with a check, it is
    something the request model must be unable to express (§5 puts user
    management on root's `/root/users`, not here).
    """

    model_config = ConfigDict(extra="forbid")

    language: Language | None = None
    email_notifications: bool | None = None
    # `email` is deliberately ABSENT. §7 scopes this endpoint to "language,
    # email_notifications, password change", and §5 puts account management on
    # root's `/root/users`. Accepting it here would also contradict what the
    # Settings view tells the user (the address is managed by whoever created
    # the account) — and it decides where §10 Channel 2 mail is delivered.
    #
    # A password change is `current_password` + `new_password` together (§7): the
    # session cookie proves who you are, the current password proves you are still
    # at the keyboard, which is what makes a stolen cookie unable to lock the owner
    # out of their own account.
    current_password: str | None = Field(default=None, min_length=1, max_length=256)
    # Max mirrors LoginIn so argon2 never sees an unbounded body. The MINIMUM is
    # enforced in the handler, not here: a Field constraint fails as a 422 whose
    # `detail` is pydantic's error LIST, which the frontend cannot map to a
    # dictionary key — so the user would read "something went wrong" instead of
    # "your password is too short" (§9).
    new_password: str | None = Field(default=None, max_length=256)


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
    # §6 (v1.7): the /export/ics feed credential — "never serialized to anyone
    # but its own user". /me IS its own user, and it is the only schema allowed
    # to carry this; it must never move up into UserOut.
    ics_token: str

    @classmethod
    def for_user(cls, user: User) -> MeOut:
        """Build from the ORM row.

        Explicit rather than `from_attributes`: capabilities are derived (§7) and
        have no column to read.
        """
        return cls(
            **UserOut.model_validate(user).model_dump(),
            capabilities=Capabilities.for_user(user),
            ics_token=user.ics_token,
        )


class UserCreateIn(BaseModel):
    """`POST /root/users` body (§5 row 7, §7 `-- root --`).

    `is_root` is structurally absent, exactly as it is from every response model.
    §5 makes root a single seeded account ("build decision: single account with
    `is_root` flag ... 5 account rows, not 6"); a second root would be a second
    holder of the one authority that can create accounts, and no endpoint may
    mint one. Root-ness is a property of the seed, not of the API.

    `active` is absent too: a created account is active. Deactivation is a PATCH
    (§5: "the root panel offers deactivate, not delete").
    """

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    role: UserRole
    email: str | None = Field(default=None, max_length=255)
    is_admin: bool = False
    language: Language = Language.IT
    # Bounded like LoginIn so argon2 never sees an unbounded body; the MINIMUM is
    # enforced in the handler so the failure is a machine code the §9 dictionaries
    # can render, not pydantic's error list.
    password: str = Field(max_length=256)


class UserUpdateIn(BaseModel):
    """`PATCH /root/users/{id}` body (§5 row 7).

    A partial patch: an absent field is left alone. `email` distinguishes absent
    from explicit `null` (clearing an address is a real operation) via
    `model_fields_set`, so None is not read as "unchanged".

    `is_root`, `username` and `password` are absent by construction: root-ness is
    never settable (see `UserCreateIn`), the username is the account's identity in
    the audit log, and a password reset is its own endpoint so that "who reset
    whose password" is a distinct audit action.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    role: UserRole | None = None
    email: str | None = Field(default=None, max_length=255)
    is_admin: bool | None = None
    language: Language | None = None
    # §5: "Users are never hard-deleted. Deactivation via users.active = false is
    # the only removal" — and it is immediate, revoking the user's open sessions.
    active: bool | None = None


class PasswordResetIn(BaseModel):
    """`POST /root/users/{id}/password` body (§5 row 7: "reset passwords").

    No `current_password`: root is not proving it is the account holder — that is
    the whole point of a reset, and the §7 self-service change on `/me/settings`
    is where the current password is required.
    """

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(max_length=256)


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
    are real coverage — while his root role stays invisible (§5).

    `id` is the §6 assignments row id — the handle `POST /swaps` names its two
    sides by (§4), so the grid can open a swap without a second endpoint."""

    id: int
    day: Day
    slot: AssignmentSlot
    role: AssignmentRole
    user_id: int
    user_name: str
    source: AssignmentSource

    @classmethod
    def from_model(cls, assignment: Assignment) -> ScheduleAssignmentOut:
        return cls(
            id=assignment.id,
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


class SwapCreateIn(BaseModel):
    """`POST /swaps` body (§7). The caller is `from_user`; the three ids name the
    target worker and the two locked assignment rows to exchange (§4)."""

    to_user: int
    from_assignment: int
    to_assignment: int


class SwapAssignmentOut(BaseModel):
    """One side of a swap as echoed on `SwapRequestOut` — the assignment row's
    identity and its (day, slot, role) shape, plus its CURRENT holder. Never a
    user object, so nothing here can grow an `is_root` (§5)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    day: Day
    slot: AssignmentSlot
    role: AssignmentRole
    user_id: int


class SwapRequestOut(BaseModel):
    """A §6 swap_request as either party sees it (§7 `GET /swaps`). Echoes the
    week by its Monday date (the §6 natural key) and both assignment rows nested,
    so the frontend renders the trade without a second lookup."""

    id: int
    week: dt.date
    from_user: int
    to_user: int
    from_assignment: SwapAssignmentOut
    to_assignment: SwapAssignmentOut
    status: SwapStatus
    created_at: dt.datetime
    resolved_at: dt.datetime | None

    @classmethod
    def from_model(cls, swap: SwapRequest) -> SwapRequestOut:
        return cls(
            id=swap.id,
            week=swap.week.monday_date,
            from_user=swap.from_user,
            to_user=swap.to_user,
            from_assignment=SwapAssignmentOut.model_validate(swap.requester_assignment),
            to_assignment=SwapAssignmentOut.model_validate(swap.target_assignment),
            status=swap.status,
            created_at=swap.created_at,
            resolved_at=swap.resolved_at,
        )


class OverrideIn(BaseModel):
    """`POST /admin/override` body (§7, §5 "Override locked slots").

    The slot is named by the §6 natural keys — the week by its Monday date, then
    (day, slot, role) — never by a surrogate assignment id, so an admin can point
    at a slot the way the schedule grid displays it.

    `assignment_id` is the one exception and is optional: the §6 unique index is
    scoped to Mon–Fri because H5 seats TWO spiaggini in every weekend slot, so on
    Sat/Sun the natural key can match two rows and the id says which. Sending it
    for a weekday is allowed but redundant; sending one that does not match the
    named (week, day, slot, role) is refused rather than silently preferred.
    """

    model_config = ConfigDict(extra="forbid")

    week: dt.date
    day: Day
    slot: AssignmentSlot
    role: AssignmentRole
    user_id: int
    assignment_id: int | None = None


class ViolationOut(BaseModel):
    """One §2.1 hard rule the overridden week no longer satisfies.

    Data, not prose (§9 renders it): `rule` is "H2", "H3" or "H4", `user_id` the
    worker it lands on, and `day`/`slot` locate it where the rule is per-day or
    per-slot. Present in the response because §5's override is deliberately
    allowed to create these — see `app.override_service` — and the admin must
    read back what they did.
    """

    rule: str
    user_id: int
    day: Day | None
    slot: AssignmentSlot | None


class OverrideOut(BaseModel):
    """`POST /admin/override` result: the row as it now stands, who held it
    before (None when the slot was empty and the row had to be created), and the
    H2–H4 violations the change left standing."""

    assignment: ScheduleAssignmentOut
    previous_user_id: int | None
    new_user_id: int
    created: bool
    violations: list[ViolationOut]


class AdminConstraintOut(BaseModel):
    """One worker's constraint as an admin sees it (§7 `GET /admin/constraints`,
    §5 "View all constraint submissions").

    Carries `user_id` + `user_name` so the panel groups submissions by person
    without a second lookup. Root's own submissions appear like anyone else's —
    §5 hides the root ROLE, not the fact that Matteo works and submits — and
    `is_root` is structurally absent here as it is everywhere.
    """

    id: int
    user_id: int
    user_name: str
    day: Day
    slot: ConstraintSlot
    kind: ConstraintKind
    note: str | None
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def from_model(cls, constraint: Constraint) -> AdminConstraintOut:
        return cls(
            id=constraint.id,
            user_id=constraint.user_id,
            user_name=constraint.user.display_name,
            day=constraint.day,
            slot=constraint.slot,
            kind=constraint.kind,
            note=constraint.note,
            created_at=constraint.created_at,
            updated_at=constraint.updated_at,
        )


class AdminConstraintsOut(BaseModel):
    """Every submission for one week (§7 `GET /admin/constraints?week=`), with the
    week's lifecycle state so the panel knows whether the window is still open."""

    week: dt.date
    status: WeekStatus
    constraints: list[AdminConstraintOut]


class AuditEntryOut(BaseModel):
    """One §6 `audit_log` row (§7 `GET /admin/audit`, §5 "View audit log").

    §6: "actor_id NULL means a system action (cron solve, 48 h swap expiry,
    nightly backup) ... There is deliberately no system user row." So the wire
    format says that outright with `system: true` and a null actor, instead of
    leaving the reader to interpret a missing name as a lookup failure or a
    deleted account — which §6 is explicit it never is ("users are never
    hard-deleted, so a NULL actor_id is never a vanished human").
    """

    id: int
    actor_id: int | None
    actor_name: str | None
    system: bool
    action: str
    entity: str
    entity_id: int | None
    payload: dict[str, object] | None
    created_at: dt.datetime

    @classmethod
    def from_model(cls, row: AuditLog) -> AuditEntryOut:
        return cls(
            id=row.id,
            actor_id=row.actor_id,
            actor_name=row.actor.display_name if row.actor is not None else None,
            system=row.actor_id is None,
            action=row.action,
            entity=row.entity,
            entity_id=row.entity_id,
            payload=row.payload,
            created_at=row.created_at,
        )


class AuditPageOut(BaseModel):
    """A page of the audit log, newest first. `total` is the count matching the
    filters (not the page), so the panel can paginate without probing."""

    total: int
    limit: int
    offset: int
    entries: list[AuditEntryOut]


class ConflictItemOut(BaseModel):
    """One blocking hard request from the §8 minimal unsat core (§6
    sacrifice_proposals.conflict) — data the §9 dictionaries render in the
    viewer's language; the API never ships prose here."""

    worker_id: int
    day: Day
    slot: ConstraintSlot


class SacrificeProposalOut(BaseModel):
    """A §2.3 sacrifice proposal as its target worker sees it (accept/decline).
    Echoes the week by Monday date and the offered free day."""

    id: int
    week: dt.date
    proposed_free_day: Day
    status: SacrificeStatus
    conflict: list[ConflictItemOut] | None
    created_at: dt.datetime

    @classmethod
    def from_model(cls, proposal: SacrificeProposal) -> SacrificeProposalOut:
        return cls(
            id=proposal.id,
            week=proposal.week.monday_date,
            proposed_free_day=proposal.proposed_free_day,
            status=proposal.status,
            conflict=(
                [ConflictItemOut.model_validate(item) for item in proposal.conflict]
                if proposal.conflict is not None
                else None
            ),
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
