"""Admin override of a locked slot (spec §5 "Override locked slots", §3.4, §7).

§3.4 leaves exactly two post-lock instruments: a peer-approved swap (§4) and this.
Where a swap is a *negotiated* exchange between two workers and is therefore
refused unless the resulting week still satisfies H2–H4, an override is the
unilateral admin act §5 grants — and the two must not be confused.

**Why an override is allowed to leave H2–H4 violated.**

§2.1 opens with "hard constraints (never violated; infeasibility triggers the
sacrifice flow)" and §8 encodes H1–H7 as constraints of the CP-SAT *model*: they
bind the solver, which is the thing that has to produce a schedule from nothing.
§5 then grants the admin an override of the *locked* result, and §3.4 names it as
one of only two ways a locked slot may move at all. An override that refused
every H2–H4 violation would be strictly weaker than the swap it sits beside and
would be unable to express the only situations that actually call for it — a
worker in hospital on Friday, a replacement who consequently works six days.
Those are precisely the cases the model cannot represent; that is why §5 hands a
human the authority instead of asking the solver again.

So: **allow, but never silently** (§2.3 step 4's principle, stated there for the
sacrifice flow and applied here for the same reason). Three things make it loud:

1. every override writes an `audit_log` row (§6) naming the actor, the row, the
   holder it displaced and the resulting violations;
2. §10's `admin_override` event fires to BOTH affected workers — the one who lost
   the slot and the one who gained it;
3. the response carries the H2/H3/H4 violations the change produced, so the
   admin reads back what they just did rather than discovering it next week.

What an override may NOT do is seat a worker in a role they cannot hold: §1 makes
bagnino/spiaggino/jolly a property of the person, not a preference, and H1's
coverage ("exactly one bagnino ∈ {...}") is a statement about who is qualified.
That check goes through `app.roles.can_hold` — the same predicate the §4 swap
validator uses, never a second copy.

**H5 weekend rows.** §2.1 H5 names override alongside swap as the only two things
that can move a weekend row, so overriding Sat/Sun is in scope — and an override
that touches Sunday must re-derive `solver_state`, exactly as an accepted weekend
swap does (`app.swap_service`): §2.2 seeds next Monday's alternation from "each
worker's last worked slot", and if the rows move without the boundary moving,
next week is planned against a Sunday that did not happen.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any, NamedTuple

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit
from app.enums import AssignmentRole, AssignmentSlot, AssignmentSource, Day, UserRole, WeekStatus
from app.models import Assignment, User, Week
from app.notifications import EVENT_ADMIN_OVERRIDE, notify
from app.publish_service import write_solver_state
from app.roles import can_hold
from app.solve_service import accepted_sacrifice_grants
from app.solver import SOLVER_DAYS, free_day_domain

_WEEKEND_DAYS = frozenset((Day.SAT, Day.SUN))

# Stable machine codes (§9 keeps user-visible strings in the i18n dictionaries).
ERROR_WEEK_NOT_FOUND = "week_not_found"  # 404
ERROR_WEEK_NOT_LOCKED = "week_not_locked"  # 409: §3.4 — override is post-lock only
ERROR_OVERRIDE_USER_NOT_FOUND = "override_user_not_found"  # 422
ERROR_OVERRIDE_USER_INACTIVE = "override_user_inactive"  # 422: §5 deactivated ≠ available
ERROR_OVERRIDE_ROLE_INVALID = "override_role_invalid"  # 422: §1/H1 qualification
ERROR_OVERRIDE_NO_CHANGE = "override_no_change"  # 409: they already hold it
ERROR_OVERRIDE_AMBIGUOUS = "override_ambiguous_slot"  # 409: H5 double-staffed slot
ERROR_OVERRIDE_ROW_MISMATCH = "override_row_mismatch"  # 422: assignment_id ≠ the named slot


class OverrideSpec(NamedTuple):
    """The slot to override, named by the §6 natural keys.

    `assignment_id` is optional and exists only for the H5 weekend: the §6 unique
    index is scoped to Mon–Fri because the template deliberately seats TWO
    spiaggini in every weekend slot, so `(week, day, slot, role)` does not
    identify a row there. Naming the row directly is the only unambiguous way to
    say *which* spiaggino is being replaced. On a weekday it is never needed.
    """

    week: dt.date
    day: Day
    slot: AssignmentSlot
    role: AssignmentRole
    user_id: int
    assignment_id: int | None = None


class Violation(NamedTuple):
    """One §2.1 hard rule the resulting week no longer satisfies, as DATA.

    Returned to the admin, recorded in the audit payload, and rendered by the §9
    dictionaries — never a pre-formatted sentence, for the same reason §6 v1.5
    made `sacrifice_proposals.conflict` structured.
    """

    rule: str
    user_id: int
    day: Day | None = None
    slot: AssignmentSlot | None = None


class OverrideOutcome(NamedTuple):
    """What the override did: the row, who it moved it from and to, whether the
    row had to be created, and the H2–H4 violations the result carries."""

    assignment: Assignment
    previous_user_id: int | None
    new_user_id: int
    created: bool
    violations: tuple[Violation, ...]


def apply_override(db: DbSession, actor: User, spec: OverrideSpec) -> OverrideOutcome:
    """§5: seat `spec.user_id` in the named locked slot. One transaction.

    Preconditions, in order (first failure raises):

    - the week exists (404) and is LOCKED (409). §3.4 puts override *after* the
      lock: before publish the schedule is not even visible, and an unpublished
      week is changed by re-solving (`POST /admin/solve`), not by hand.
    - the target user exists, is active (§5: deactivation is the only removal, and
      a removed worker is not an eligible holder) and can hold the row's role
      (§1/H1, via `app.roles.can_hold` — the swap validator's own predicate).
    - the named slot resolves to at most one row (see `OverrideSpec.assignment_id`).
    - the target does not already hold it: an override that changes nothing must
      not produce an audit row and two notifications claiming it did (409).

    H2–H4 are deliberately NOT preconditions — see the module docstring. They are
    computed after the change and returned.
    """
    week = db.scalar(select(Week).where(Week.monday_date == spec.week))
    if week is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_WEEK_NOT_FOUND)
    if week.status is not WeekStatus.LOCKED:
        # §3.4: post-lock changes are swap or override. An OPEN/SOLVED week has no
        # published slots to override — it is (re)generated instead (§3.2).
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_WEEK_NOT_LOCKED)

    target = db.get(User, spec.user_id)
    if target is None:
        raise _invalid(ERROR_OVERRIDE_USER_NOT_FOUND)
    if not target.active:
        raise _invalid(ERROR_OVERRIDE_USER_INACTIVE)
    if not can_hold(target.role, spec.role):
        # §1: role is a property of the person; H1's coverage names *qualified*
        # holders. This is the one rule an override may not bend.
        raise _invalid(ERROR_OVERRIDE_ROLE_INVALID)

    row = _resolve_row(db, week, spec)
    created = row is None
    previous_user_id = None if row is None else row.user_id
    if previous_user_id == spec.user_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_OVERRIDE_NO_CHANGE)

    if row is None:
        row = Assignment(
            week_id=week.id,
            day=spec.day,
            slot=spec.slot,
            role=spec.role,
            user_id=spec.user_id,
            source=AssignmentSource.OVERRIDE,
        )
        db.add(row)
    else:
        row.user_id = spec.user_id
        row.source = AssignmentSource.OVERRIDE
    db.flush()  # the change must be visible to the violation scan and the boundary

    if spec.day in _WEEKEND_DAYS:
        # §2.1 H5 lets an override move a weekend row; §2.2 seeds next Monday's
        # alternation from the Sunday that ACTUALLY happened. Same reasoning (and
        # same idempotent helper) as an accepted weekend swap in `app.swap_service`
        # — re-derive here or next week is planned against a fiction.
        write_solver_state(db, week)

    affected = [uid for uid in (previous_user_id, spec.user_id) if uid is not None]
    violations = week_violations(db, week, affected)

    audit.record(
        db,
        actor,
        audit.ACTION_OVERRIDE,
        "assignment",
        row.id,
        {
            "week": week.monday_date.isoformat(),
            "day": spec.day.value,
            "slot": spec.slot.value,
            "role": spec.role.value,
            "previous_user_id": previous_user_id,
            "user_id": spec.user_id,
            "created": created,
            # §2.1: an override may leave these standing, but never silently.
            "violations": [_violation_payload(v) for v in violations],
        },
    )
    _fan_out(db, week, spec, previous_user_id)
    db.commit()
    return OverrideOutcome(
        assignment=row,
        previous_user_id=previous_user_id,
        new_user_id=spec.user_id,
        created=created,
        violations=violations,
    )


def _resolve_row(db: DbSession, week: Week, spec: OverrideSpec) -> Assignment | None:
    """The single §6 `assignments` row the spec names, or None if the slot is empty.

    Mon–Fri: the partial unique index guarantees at most one match, so the natural
    key suffices. Sat/Sun: the H5 template seats two spiaggini per slot, so the key
    can match two rows — `assignment_id` disambiguates, and without it the request
    is refused (409) rather than replacing whichever row the database returned
    first.
    """
    stmt = select(Assignment).where(
        Assignment.week_id == week.id,
        Assignment.day == spec.day,
        Assignment.slot == spec.slot,
        Assignment.role == spec.role,
    )
    matches = list(db.scalars(stmt).all())
    if spec.assignment_id is not None:
        named = next((a for a in matches if a.id == spec.assignment_id), None)
        if named is None:
            # The id exists but describes a different slot (or nothing): refuse
            # rather than silently honouring one of the two conflicting keys.
            raise _invalid(ERROR_OVERRIDE_ROW_MISMATCH)
        return named
    if len(matches) > 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERROR_OVERRIDE_AMBIGUOUS)
    return matches[0] if matches else None


def week_violations(db: DbSession, week: Week, user_ids: list[int]) -> tuple[Violation, ...]:
    """The §2.1 H2/H3/H4 rules `user_ids` no longer satisfy in `week`, as data.

    Evaluated against the week's persisted rows *after* the change, for the
    affected workers only. Their *own* rows are the only ones that moved, but H3(c)
    (v1.12) is a pairwise rule, so a violation can name an affected worker while
    the day it collides on belongs to an untouched same-role partner — the pair is
    read from the whole week and reported against the worker who was moved.

    Scope mirrors the §4 swap validator exactly: H2 ranges over the whole week
    (holding two roles at one instant is impossible on any day), H3/H4 over Mon–Fri
    only (H5's weekend is a template whose full-day workers legitimately hold two
    slots a day), the jolly is exempt from H3/H4 (H6), and H3's three clauses are
    all checked — (a) exactly one free weekday, (b) inside the worker's ROLE domain
    ({Mon, Tue} spiaggini, {Tue, Wed} bagnini) widened by the week's accepted §2.3
    grant, (c) no same-role pair sharing a free day. The domain comes from the
    solver's `free_day_domain` and the grant from `accepted_sacrifice_grants` —
    the same two helpers every solve uses, never a local copy.

    Each H3 clause reports under its own rule id ("H3", "H3_ROLE_DOMAIN",
    "H3_SHARED_FREE_DAY") so §9 can name the real reason; at most one fires per
    worker, the clauses being checked in order.
    """
    rows = list(db.scalars(select(Assignment).where(Assignment.week_id == week.id)).all())
    grants = accepted_sacrifice_grants(db, week)
    free_days = _free_weekdays(db, rows)
    found: list[Violation] = []
    for uid in user_ids:
        user = db.get(User, uid)
        if user is None:
            continue
        held = [a for a in rows if a.user_id == uid]
        # H2: at most one role per (day, slot).
        for (day, slot), count in sorted(
            Counter((a.day, a.slot) for a in held).items(), key=lambda kv: (kv[0][0], kv[0][1])
        ):
            if count > 1:
                found.append(Violation("H2", uid, day, slot))
        if user.role is UserRole.JOLLY:
            continue  # H6: the jolly may double and holds no H3 free day
        day_counts = Counter(a.day for a in held if a.day in SOLVER_DAYS)
        # H4: a core worker works at most one slot per weekday.
        for day in SOLVER_DAYS:
            if day_counts[day] > 1:
                found.append(Violation("H4", uid, day))
        # H3 is three clauses (v1.12) and each reports under its OWN rule id: one
        # shared id could only be rendered with one sentence, which would show the
        # admin a WRONG reason for two of the three (§9 owns the sentences, but the
        # rule id is what lets it pick the right one).
        # H3(a): exactly one free weekday.
        free = [d for d in SOLVER_DAYS if day_counts[d] == 0]
        if len(free) != 1:
            found.append(Violation("H3", uid))
            continue
        # H3(b): that day is inside the role domain ∪ {grant}.
        if free[0] not in free_day_domain(user.role, uid, grants):
            found.append(Violation("H3_ROLE_DOMAIN", uid, free[0]))
            continue
        # H3(c): no same-role worker rests on the same day. Reported against the
        # moved worker and located on the shared day; the colliding partner is
        # derivable from the week but deliberately not carried in the payload.
        if any(
            other != uid and role is user.role and free[0] in days
            for other, (role, days) in free_days.items()
        ):
            found.append(Violation("H3_SHARED_FREE_DAY", uid, free[0]))
    return tuple(found)


def _free_weekdays(
    db: DbSession, rows: list[Assignment]
) -> dict[int, tuple[UserRole, frozenset[Day]]]:
    """Every CORE worker holding rows in the week, with their role and the weekdays
    they work no slot on. Feeds the pairwise H3(c) check, which — unlike (a)/(b) —
    cannot be decided from the affected worker's rows alone. The jolly is omitted
    (H6: no free day to share)."""
    worked: dict[int, set[Day]] = {}
    for a in rows:
        days = worked.setdefault(a.user_id, set())
        if a.day in SOLVER_DAYS:
            days.add(a.day)
    out: dict[int, tuple[UserRole, frozenset[Day]]] = {}
    for uid, days in worked.items():
        user = db.get(User, uid)
        if user is None or user.role is UserRole.JOLLY:
            continue
        out[uid] = (user.role, frozenset(d for d in SOLVER_DAYS if d not in days))
    return out


def _fan_out(db: DbSession, week: Week, spec: OverrideSpec, previous_user_id: int | None) -> None:
    """§10 `admin_override` → the worker who LOST the slot and the one who GAINED
    it. Both are affected (§12 Phase 6: "notifies affected workers").

    Addressed individually, not by role, so root receives it as an ordinary worker
    when one of his own shifts moves — §5 hides the root ROLE from role-based
    fan-outs, not the man from news about his own schedule. Deduped in the
    unreachable case where the two ids coincide (the no-change guard rejects it
    first), and the previous holder is absent when the row was created empty.
    """
    payload: dict[str, Any] = {
        "week": week.monday_date.isoformat(),
        "day": spec.day.value,
        "slot": spec.slot.value,
        "role": spec.role.value,
        "previous_user_id": previous_user_id,
        "user_id": spec.user_id,
    }
    recipients: dict[int, User] = {}
    for uid in (previous_user_id, spec.user_id):
        if uid is None:
            continue
        user = db.get(User, uid)
        if user is not None:
            recipients[user.id] = user
    for user in recipients.values():
        notify(db, user, EVENT_ADMIN_OVERRIDE, payload)


def _violation_payload(violation: Violation) -> dict[str, Any]:
    return {
        "rule": violation.rule,
        "user_id": violation.user_id,
        "day": violation.day.value if violation.day is not None else None,
        "slot": violation.slot.value if violation.slot is not None else None,
    }


def _invalid(code: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=code)
