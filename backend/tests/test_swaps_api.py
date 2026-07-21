"""Peer-approved swaps (spec §4, §7 `/swaps`, §10) — the Phase 4 gate suite.

The §12 gate names two criteria: a role-invalid swap is rejected, and a valid
swap applies atomically and audit-logs. Both are here, along with the rest of
§4: validation at creation AND again at acceptance, H2–H4 for both parties, the
H5 weekend restriction, the `REQUIRE_ADMIN_APPROVAL` fork, and the 48 h timeout.

Swaps are located by SHAPE, never by hardcoded row id: each test states the
schedule feature it needs ("two bagnino rows on one day, different core
holders") and `_find_*` asserts the precondition was met. If the solver's output
ever changes, these fail with "no such pair in this week" rather than silently
swapping something else and proving nothing.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.enums import (
    AssignmentRole,
    AssignmentSlot,
    AssignmentSource,
    Day,
    SacrificeStatus,
    SwapStatus,
    UserRole,
    WeekStatus,
)
from app.jobs import expire_stale_swaps
from app.models import (
    Assignment,
    AuditLog,
    Notification,
    SacrificeProposal,
    SolverState,
    SwapRequest,
    User,
    Week,
)
from app.notifications import EVENT_SWAP_ACCEPTED, EVENT_SWAP_REJECTED, EVENT_SWAP_REQUESTED
from app.publish_service import publish_week
from app.scheduling import get_or_create_week
from app.solve_service import run_solve
from app.solver import FREE_DAYS, SOLVER_DAYS
from app.swap_service import SWAP_TTL
from tests.factories import PASSWORD, create_full_roster

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase4

_WEEKEND = (Day.SAT, Day.SUN)


def _future_monday(weeks_ahead: int = 2) -> dt.date:
    today = dt.datetime.now(dt.UTC).date()
    next_monday = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)
    return next_monday + dt.timedelta(weeks=weeks_ahead - 1)


def login(client: TestClient, username: str) -> None:
    resp = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _published_week(session: DbSession, roster: dict[str, User], monday: dt.date) -> Week:
    """A real LOCKED week: solve, then publish. Swaps are the post-lock
    instrument (§3.4), so every swap test needs one."""
    week = get_or_create_week(session, monday)
    result = run_solve(session, week)
    assert result.status.value in ("optimal", "feasible"), "the fixture week must solve"
    publish_week(session, week, roster["mattia"])
    session.commit()
    session.refresh(week)
    assert week.status is WeekStatus.LOCKED
    return week


def _rows(session: DbSession, week: Week) -> list[Assignment]:
    return list(session.scalars(select(Assignment).where(Assignment.week_id == week.id)).all())


# CP-SAT may return any optimum, and equally-optimal schedules differ between
# machines. So no test may assume a particular week: each states the SHAPE it
# needs as a predicate, searches the week the solver actually produced, and
# fails loudly if that shape is absent. These helpers model the §2.1 rules well
# enough to CHOOSE a scenario — never to assert an outcome, which is always the
# server's own answer.
_Held = set[tuple[Day, AssignmentSlot, AssignmentRole]]


def _held_after(rows: list[Assignment], user_id: int, give: Assignment, take: Assignment) -> _Held:
    """What this party would hold once the two rows change hands."""
    held = {(a.day, a.slot, a.role) for a in rows if a.user_id == user_id}
    held.discard((give.day, give.slot, give.role))
    held.add((take.day, take.slot, take.role))
    return held


def _h2_ok(held: _Held) -> bool:
    """H2: at most one role per (day, slot)."""
    slots = [(day, slot) for day, slot, _ in held]
    return len(slots) == len(set(slots))


def _h4_ok(held: _Held) -> bool:
    """H4: a core worker works at most one slot per weekday."""
    weekdays = [day for day, _, _ in held if day in SOLVER_DAYS]
    return len(weekdays) == len(set(weekdays))


def _free_after(held: _Held) -> set[Day]:
    """The weekdays this party would have off."""
    return set(SOLVER_DAYS) - {day for day, _, _ in held if day in SOLVER_DAYS}


def _role_compatible(user_role: UserRole, row_role: AssignmentRole) -> bool:
    """§4: bagnino↔bagnino, spiaggino↔spiaggino; the jolly holds either."""
    return user_role is UserRole.JOLLY or user_role.value == row_role.value


def _legal_after(
    rows: list[Assignment], user_id: int, give: Assignment, take: Assignment, *, core: bool
) -> bool:
    """Would this party still satisfy H2 (+ H3/H4 if core) after the exchange?"""
    held = _held_after(rows, user_id, give, take)
    if not _h2_ok(held):
        return False
    if not core:
        return True  # H6: the jolly may double and holds no H3 free day
    if not _h4_ok(held):
        return False
    free = _free_after(held)
    return len(free) == 1 and next(iter(free)) in FREE_DAYS  # H3


def _legal_exchanges(
    session: DbSession, rows: list[Assignment]
) -> list[tuple[Assignment, Assignment]]:
    """Every (mine, theirs) pair this week admits as a fully valid §4 swap."""
    found: list[tuple[Assignment, Assignment]] = []
    for mine in rows:
        for theirs in rows:
            if mine.user_id == theirs.user_id:
                continue
            requester = session.get(User, mine.user_id)
            target = session.get(User, theirs.user_id)
            assert requester is not None and target is not None
            # H5: a swap touching the weekend is bagnino↔bagnino or nothing.
            touches_weekend = mine.day in _WEEKEND or theirs.day in _WEEKEND
            if touches_weekend and {mine.role, theirs.role} != {AssignmentRole.BAGNINO}:
                continue
            if not _role_compatible(requester.role, theirs.role):
                continue
            if not _role_compatible(target.role, mine.role):
                continue
            if not _legal_after(
                rows, requester.id, mine, theirs, core=requester.role is not UserRole.JOLLY
            ):
                continue
            if not _legal_after(
                rows, target.id, theirs, mine, core=target.role is not UserRole.JOLLY
            ):
                continue
            found.append((mine, theirs))
    return found


def _worked_weekdays(rows: list[Assignment], user_id: int) -> set[Day]:
    return {a.day for a in rows if a.user_id == user_id and a.day in SOLVER_DAYS}


def _free_weekday(rows: list[Assignment], user_id: int) -> Day:
    """The worker's single H3 free day in this week."""
    free = set(SOLVER_DAYS) - _worked_weekdays(rows, user_id)
    assert len(free) == 1, f"user {user_id} must have exactly one free weekday, got {free}"
    return next(iter(free))


def _find_friday_free_day_exchange(
    session: DbSession, rows: list[Assignment]
) -> tuple[Assignment, Assignment] | None:
    """An exchange that would leave the REQUESTER resting on Friday — legal only
    under a §2.3 grant (§2.1 H3). Everything else about it is valid, and the
    other party stays legal, so the only rule it can break is the requester's
    H3 domain. That makes it the exact pair for the without-grant refusal and
    the with-grant acceptance, which must differ ONLY in the grant."""
    for mine in rows:
        requester = session.get(User, mine.user_id)
        assert requester is not None
        if requester.role is UserRole.JOLLY or mine.day in _WEEKEND:
            continue
        for theirs in rows:
            target = session.get(User, theirs.user_id)
            assert target is not None
            if target.id == requester.id or theirs.day in _WEEKEND:
                continue
            if not _role_compatible(requester.role, theirs.role):
                continue
            if not _role_compatible(target.role, mine.role):
                continue
            held = _held_after(rows, requester.id, mine, theirs)
            # Everything holds for the requester EXCEPT that their one free day
            # would fall on Friday.
            if not (_h2_ok(held) and _h4_ok(held)):
                continue
            if _free_after(held) != {Day.FRI}:
                continue
            if not _legal_after(
                rows, target.id, theirs, mine, core=target.role is not UserRole.JOLLY
            ):
                continue
            return mine, theirs
    return None


def _find_same_day_pair(
    rows: list[Assignment], roster: dict[str, User], role: AssignmentRole
) -> tuple[Assignment, Assignment]:
    """Two weekday rows of the SAME role on the SAME day, held by two different
    CORE workers — the canonical valid swap: each party keeps one slot that day,
    so H3 and H4 are untouched by construction."""
    core = {u.id for u in roster.values() if u.role is not UserRole.JOLLY}
    for day in SOLVER_DAYS:
        same_day = [a for a in rows if a.day is day and a.role is role and a.user_id in core]
        if len({a.user_id for a in same_day}) == 2:
            first, second = sorted(same_day, key=lambda a: a.slot.value)
            return first, second
    raise AssertionError(f"no weekday holds two core {role.value} rows in this week")


def _create(
    client: TestClient, target: User, mine: Assignment, theirs: Assignment
) -> tuple[int, dict]:
    resp = client.post(
        "/api/swaps",
        json={
            "to_user": target.id,
            "from_assignment": mine.id,
            "to_assignment": theirs.id,
        },
    )
    return resp.status_code, resp.json()


def _audit_rows(session: DbSession, transition: str) -> list[AuditLog]:
    return [
        row
        for row in session.scalars(select(AuditLog).where(AuditLog.action == "swap")).all()
        if (row.payload or {}).get("transition") == transition
    ]


def _notes(session: DbSession, event: str) -> list[Notification]:
    return list(session.scalars(select(Notification).where(Notification.event_type == event)).all())


# --- the gate criterion: a valid swap applies atomically and audit-logs -------


def test_valid_swap_applies_atomically_and_audit_logs(
    client: TestClient, session: DbSession
) -> None:
    """§12 Phase 4 gate + §4: two core bagnini trade slots on the same day. On
    acceptance the two rows exchange holders in ONE transaction, both are
    restamped `source=swap`, the request lands `applied`, and exactly one audit
    row records the exchange."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    mine, theirs = _find_same_day_pair(rows, roster, AssignmentRole.BAGNINO)
    requester = session.get(User, mine.user_id)
    target = session.get(User, theirs.user_id)
    assert requester is not None and target is not None

    login(client, requester.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 201, body
    assert body["status"] == "pending"
    swap_id = body["id"]

    login(client, target.username)
    resp = client.post(f"/api/swaps/{swap_id}/accept")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "applied"

    session.expire_all()
    applied_mine = session.get(Assignment, mine.id)
    applied_theirs = session.get(Assignment, theirs.id)
    assert applied_mine is not None and applied_theirs is not None
    # The exchange: each row is now held by the other party.
    assert applied_mine.user_id == target.id
    assert applied_theirs.user_id == requester.id
    # Provenance (§6 assignments.source): both rows are now swap-authored, so a
    # later regenerate leaves them alone.
    assert applied_mine.source is AssignmentSource.SWAP
    assert applied_theirs.source is AssignmentSource.SWAP

    swap = session.get(SwapRequest, swap_id)
    assert swap is not None
    assert swap.status is SwapStatus.APPLIED
    assert swap.resolved_at is not None

    applies = _audit_rows(session, "apply")
    assert len(applies) == 1, "exactly one audit row per applied swap"
    payload = applies[0].payload or {}
    assert payload["from_assignment"] == mine.id
    assert payload["to_assignment"] == theirs.id
    assert {payload["from_user"], payload["to_user"]} == {requester.id, target.id}


def test_swap_accepted_notifies_both_parties_and_the_visible_admin_only(
    client: TestClient, session: DbSession
) -> None:
    """§4 "both parties + admin notified" / §10: the role-based half of the
    fan-out goes through the visible-admin helper, so root (Matteo) is excluded
    from it (§5) — he is notified here only when he is himself a party."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    # A pair with NEITHER party being root, so root's only possible route into
    # the fan-out is the (forbidden) role-based one.
    mine, theirs = _find_same_day_pair(rows, roster, AssignmentRole.SPIAGGINO)
    requester = session.get(User, mine.user_id)
    target = session.get(User, theirs.user_id)
    assert requester is not None and target is not None
    assert roster["matteo"].id not in (requester.id, target.id), "root must not be a party here"

    login(client, requester.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 201, body
    # §10: the addressed worker — and only they — learn a request awaits.
    assert [n.user_id for n in _notes(session, EVENT_SWAP_REQUESTED)] == [target.id]

    login(client, target.username)
    assert client.post(f"/api/swaps/{body['id']}/accept").status_code == 200

    session.expire_all()
    told = {n.user_id for n in _notes(session, EVENT_SWAP_ACCEPTED)}
    assert told == {requester.id, target.id, roster["mattia"].id}
    assert roster["matteo"].id not in told, "§5: root is excluded from role-based fan-out"


def test_root_as_a_party_is_notified_like_any_worker(
    client: TestClient, session: DbSession
) -> None:
    """§5 the other way round: root's invisibility hides the root ROLE, not the
    man. Matteo works real shifts, so when he is a party to a swap he is
    notified as one."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    matteo = roster["matteo"]
    pair = next(
        (
            (mine, theirs)
            for mine, theirs in _legal_exchanges(session, rows)
            if mine.user_id == matteo.id
        ),
        None,
    )
    assert pair is not None, "this week offers root no legal swap to be a party to"
    mine, theirs = pair
    target = session.get(User, theirs.user_id)
    assert target is not None

    login(client, matteo.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 201, body
    login(client, target.username)
    assert client.post(f"/api/swaps/{body['id']}/accept").status_code == 200

    session.expire_all()
    told = {n.user_id for n in _notes(session, EVENT_SWAP_ACCEPTED)}
    assert matteo.id in told, "root as a PARTY is a worker like any other"


# --- the gate criterion: a role-invalid swap is rejected ---------------------


def test_role_invalid_swap_is_rejected_at_creation(client: TestClient, session: DbSession) -> None:
    """§12 Phase 4 gate + §4: bagnino↔spiaggino is refused. A core bagnino
    cannot hold a spiaggino row, whoever asks."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    day = next(
        d
        for d in SOLVER_DAYS
        if any(
            a.day is d
            and a.role is AssignmentRole.BAGNINO
            and session.get(User, a.user_id).role is UserRole.BAGNINO
            for a in rows
        )
        and any(
            a.day is d
            and a.role is AssignmentRole.SPIAGGINO
            and session.get(User, a.user_id).role is UserRole.SPIAGGINO
            for a in rows
        )
    )
    bagnino_row = next(
        a
        for a in rows
        if a.day is day
        and a.role is AssignmentRole.BAGNINO
        and session.get(User, a.user_id).role is UserRole.BAGNINO
    )
    spiaggino_row = next(
        a
        for a in rows
        if a.day is day
        and a.role is AssignmentRole.SPIAGGINO
        and session.get(User, a.user_id).role is UserRole.SPIAGGINO
    )
    requester = session.get(User, bagnino_row.user_id)
    target = session.get(User, spiaggino_row.user_id)
    assert requester is not None and target is not None

    login(client, requester.username)
    code, body = _create(client, target, bagnino_row, spiaggino_row)
    assert code == 422, body
    assert body["detail"] == "swap_role_invalid"
    # Nothing was written: a refused swap leaves no row behind.
    assert session.scalars(select(SwapRequest)).all() == []


def test_role_validity_is_rechecked_at_acceptance(client: TestClient, session: DbSession) -> None:
    """§4: "validated server-side before creation AND AGAIN at acceptance". A
    swap valid when proposed but invalidated since — here the requester's row
    changed hands, so it is no longer theirs to trade — is refused on accept,
    and the schedule is left untouched."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    mine, theirs = _find_same_day_pair(rows, roster, AssignmentRole.BAGNINO)
    requester = session.get(User, mine.user_id)
    target = session.get(User, theirs.user_id)
    assert requester is not None and target is not None

    login(client, requester.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 201, body

    # The world moves under the request: an override (§5) hands the requester's
    # row to someone else, so the trade they proposed is no longer theirs.
    other = roster["mattia"]
    mine_row = session.get(Assignment, mine.id)
    assert mine_row is not None
    mine_row.user_id = other.id
    mine_row.source = AssignmentSource.OVERRIDE
    session.commit()

    login(client, target.username)
    resp = client.post(f"/api/swaps/{body['id']}/accept")
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "swap_wrong_holder"

    session.expire_all()
    # Atomicity: the refused acceptance changed NOTHING.
    assert session.get(Assignment, mine.id).user_id == other.id  # the override stands
    assert session.get(Assignment, theirs.id).user_id == target.id  # untouched
    assert session.get(SwapRequest, body["id"]).status is SwapStatus.PENDING
    assert _audit_rows(session, "apply") == []


def test_the_jolly_may_take_either_role(client: TestClient, session: DbSession) -> None:
    """§1/§4 control for the role rule: Mattia matches either role, so a swap
    handing him a row is accepted whichever role it carries — the refusal above
    is about role compatibility, not about swaps being hard to make."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    mattia = roster["mattia"]
    mattia_rows = [a for a in rows if a.user_id == mattia.id and a.day in SOLVER_DAYS]
    assert mattia_rows, "the jolly must work somewhere in this week"

    candidate = next(
        (
            (mine, theirs)
            for mine, theirs in _legal_exchanges(session, rows)
            if theirs.user_id == mattia.id
        ),
        None,
    )
    assert candidate is not None, "this week offers no legal core/jolly exchange"
    mine, theirs = candidate
    requester = session.get(User, mine.user_id)
    assert requester is not None

    login(client, requester.username)
    code, body = _create(client, mattia, mine, theirs)
    assert code == 201, body
    login(client, mattia.username)
    assert client.post(f"/api/swaps/{body['id']}/accept").status_code == 200

    session.expire_all()
    assert session.get(Assignment, mine.id).user_id == mattia.id


# --- H2 / H3 / H4 hold for BOTH parties after the exchange (§4) --------------


def test_h4_violation_is_refused(client: TestClient, session: DbSession) -> None:
    """§4/H4: a core worker may not end up working two slots of one weekday.
    Trading into a day the requester already works does exactly that."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    core = [u for u in roster.values() if u.role is not UserRole.JOLLY]
    pair = next(
        (
            (mine, theirs)
            for requester in core
            for mine in rows
            if mine.user_id == requester.id and mine.day in SOLVER_DAYS
            for theirs in rows
            if theirs.role is mine.role
            and theirs.user_id != requester.id
            and theirs.day in SOLVER_DAYS
            and theirs.day is not mine.day
            # The requester already works the day they would trade INTO.
            and theirs.day in _worked_weekdays(rows, requester.id)
            and session.get(User, theirs.user_id).role is not UserRole.JOLLY
        ),
        None,
    )
    assert pair is not None, "this week offers no cross-day same-role pair"
    mine, theirs = pair
    requester = session.get(User, mine.user_id)
    target = session.get(User, theirs.user_id)
    assert requester is not None and target is not None

    login(client, requester.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 422, body
    # H4 for one party or the other — the swap is refused by the day-count rule.
    assert body["detail"] in ("swap_h4_violation", "swap_h3_violation")
    assert session.scalars(select(SwapRequest)).all() == []


def test_h3_violation_when_the_free_day_would_land_on_friday(
    client: TestClient, session: DbSession
) -> None:
    """§4/§2.1 H3: a core worker's free day must stay inside Mon–Thu. Trading a
    Friday slot for a slot on the worker's current free day pushes the free day
    onto Friday — outside the default domain — so the swap is refused.

    The other party is required to remain legal, so the refusal can only be the
    requester's H3 — and the requester is the party validated first."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    pair = _find_friday_free_day_exchange(session, rows)
    assert pair is not None, "this week offers no exchange pushing a free day to Friday"
    mine, theirs = pair
    requester = session.get(User, mine.user_id)
    target = session.get(User, theirs.user_id)
    assert requester is not None and target is not None

    login(client, requester.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 422, body
    assert body["detail"] == "swap_h3_violation"


def test_an_accepted_sacrifice_grant_makes_the_friday_free_day_legal(
    client: TestClient, session: DbSession
) -> None:
    """§2.1 H3 grant of record (v1.6) reaching §4: the SAME swap refused above is
    ACCEPTED when the worker holds an accepted sacrifice proposal for Friday —
    the grant extends their free-day domain to Mon–Thu ∪ {Fri}, and the swap
    validator reads that grant through the same helper the solver does. Without
    the shared helper the two would disagree about what H3 permits."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    pair = _find_friday_free_day_exchange(session, rows)
    assert pair is not None, "this week offers no exchange pushing a free day to Friday"
    mine, theirs = pair
    requester = session.get(User, mine.user_id)
    target = session.get(User, theirs.user_id)
    assert requester is not None and target is not None

    # The grant of record: an ACCEPTED §2.3 proposal moving this worker's free
    # day to Friday for this week.
    session.add(
        SacrificeProposal(
            week_id=week.id,
            user_id=requester.id,
            proposed_free_day=Day.FRI,
            status=SacrificeStatus.ACCEPTED,
            conflict=[{"worker_id": requester.id, "day": "fri", "slot": "full_day"}],
        )
    )
    session.commit()

    login(client, requester.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 201, f"the grant must widen H3's domain for the swap validator too: {body}"


def test_h2_violation_is_refused(client: TestClient, session: DbSession) -> None:
    """§4/H2: nobody may hold two roles in one (day, slot). The jolly is the only
    worker who can reach this state — he already doubles (H6) — and H2 is
    checked for him even though H3/H4 are not."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    mattia = roster["mattia"]

    # The jolly gives up one of his rows and takes another worker's, landing him
    # in two roles at once. The OTHER party must stay legal, so the refusal is
    # unambiguously H2 — and the jolly is the requester, hence validated first.
    scenario = next(
        (
            (give, take)
            for give in rows
            if give.user_id == mattia.id
            for take in rows
            if take.user_id != mattia.id
            and _role_compatible(session.get(User, take.user_id).role, give.role)
            and take.day not in _WEEKEND
            and give.day not in _WEEKEND
            and not _h2_ok(_held_after(rows, mattia.id, give, take))
            and _legal_after(rows, take.user_id, take, give, core=True)
        ),
        None,
    )
    assert scenario is not None, "this week offers the jolly no H2-violating exchange"
    give, take = scenario
    target = session.get(User, take.user_id)
    assert target is not None

    login(client, mattia.username)
    code, body = _create(client, target, give, take)
    assert code == 422, body
    assert body["detail"] == "swap_h2_violation"


# --- H5: the weekend template is bagnino-only territory ----------------------


def test_weekend_bagnino_swap_is_allowed(client: TestClient, session: DbSession) -> None:
    """§2.1 H5: weekend rows are "modifiable only via post-lock swap
    (bagnino↔bagnino) or admin override" — so the bagnino case is permitted."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    weekend_bagnini = [a for a in rows if a.day in _WEEKEND and a.role is AssignmentRole.BAGNINO]
    day = next(d for d in _WEEKEND if len({a.user_id for a in weekend_bagnini if a.day is d}) == 2)
    mine, theirs = sorted([a for a in weekend_bagnini if a.day is day], key=lambda a: a.slot.value)
    requester = session.get(User, mine.user_id)
    target = session.get(User, theirs.user_id)
    assert requester is not None and target is not None

    login(client, requester.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 201, body
    login(client, target.username)
    assert client.post(f"/api/swaps/{body['id']}/accept").status_code == 200

    session.expire_all()
    assert session.get(Assignment, mine.id).user_id == target.id


def test_a_sunday_swap_re_seeds_next_weeks_alternation_boundary(
    client: TestClient, session: DbSession
) -> None:
    """§2.2/§8: `solver_state` holds each worker's LAST WORKED SLOT — a fact
    about what happened, not about what was planned. Publishing derives it from
    the weekend rows; an H5 Sunday bagnino swap then MOVES those rows, and §2.2
    names exactly this pair as next Monday's alternation seed ("Matteo exits
    Sunday on PM, Francesco on AM"). If the boundary were still derived from
    the ideal template, next week would be seeded from a Sunday that never
    happened — and inverted for both of them at once."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    sunday_bagnini = [a for a in rows if a.day is Day.SUN and a.role is AssignmentRole.BAGNINO]
    assert len({a.user_id for a in sunday_bagnini}) == 2, "H5 puts two bagnini on Sunday"
    mine, theirs = sorted(sunday_bagnini, key=lambda a: a.slot.value)
    requester = session.get(User, mine.user_id)
    target = session.get(User, theirs.user_id)
    assert requester is not None and target is not None

    before = {
        state.user_id: state.last_worked_slot
        for state in session.scalars(select(SolverState)).all()
    }
    assert before[requester.id] is not before[target.id], (
        "precondition: the two Sunday bagnini exit on opposite slots"
    )

    login(client, requester.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 201, body
    login(client, target.username)
    assert client.post(f"/api/swaps/{body['id']}/accept").status_code == 200

    session.expire_all()
    after = {
        state.user_id: state.last_worked_slot
        for state in session.scalars(select(SolverState)).all()
    }
    # The two swapped their Sunday slots, so their boundaries must have swapped
    # with them — read back from the rows, not from the template.
    assert after[requester.id] == before[target.id]
    assert after[target.id] == before[requester.id]
    # And the stored boundary agrees with the schedule as it now stands.
    for party in (requester, target):
        sunday_row = next(
            a
            for a in _rows(session, week)
            if a.day is Day.SUN and a.user_id == party.id and a.role is AssignmentRole.BAGNINO
        )
        assert after[party.id] == sunday_row.slot, (
            "solver_state must describe the Sunday that actually happened"
        )


def test_a_saturday_for_sunday_swap_clears_the_vacated_boundary(
    client: TestClient, session: DbSession
) -> None:
    """§2.2: the `solver_state` write set is AUTHORITATIVE, not additive.

    An H5-legal Sat↔Sun bagnino trade moves one bagnino OFF Sunday entirely —
    he ends holding both Saturday slots while the other holds both Sunday
    slots. H2 permits it (distinct (day, slot) keys) and H3/H4 never look at the
    weekend, so the swap applies. A merely-upserting write would leave the
    vacated worker's row behind, seeding next Monday's alternation from a Sunday
    he did not work. §2.2 wants his boundary term ABSENT, exactly as the
    jolly's is."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    sat = next(a for a in rows if a.day is Day.SAT and a.role is AssignmentRole.BAGNINO)
    # The other bagnino's SUNDAY row — so the trade crosses days.
    sun = next(
        a
        for a in rows
        if a.day is Day.SUN and a.role is AssignmentRole.BAGNINO and a.user_id != sat.user_id
    )
    requester = session.get(User, sat.user_id)
    target = session.get(User, sun.user_id)
    assert requester is not None and target is not None
    assert session.get(SolverState, target.id) is not None, (
        "precondition: the Sunday holder starts with a boundary"
    )

    login(client, requester.username)
    code, body = _create(client, target, sat, sun)
    assert code == 201, body
    login(client, target.username)
    assert client.post(f"/api/swaps/{body['id']}/accept").status_code == 200

    session.expire_all()
    # The target gave up his only Sunday row → no boundary at all.
    remaining_sunday = {
        a.user_id
        for a in _rows(session, week)
        if a.day is Day.SUN and a.role is AssignmentRole.BAGNINO
    }
    assert target.id not in remaining_sunday, "precondition: he really left Sunday"
    assert session.get(SolverState, target.id) is None, (
        "a worker with no Sunday row must carry no boundary (§2.2)"
    )
    # ... and the worker who took both Sunday slots reads as a FULL_DAY boundary,
    # which the single am/pm column holds as NULL (§6).
    state = session.get(SolverState, requester.id)
    assert state is not None and state.last_worked_slot is None


def test_a_swap_never_overwrites_a_newer_weeks_boundary(
    client: TestClient, session: DbSession
) -> None:
    """§6 dates the boundary for a reason. A swap on week N stays acceptable
    after week N+1 has published, and must not drag the boundary back to N's
    older Sunday — `last_worked_date` is what orders the two."""
    roster = create_full_roster(session)
    first = _published_week(session, roster, _future_monday())
    second = _published_week(session, roster, _future_monday() + dt.timedelta(weeks=1))
    newer = {
        state.user_id: (state.last_worked_slot, state.last_worked_date)
        for state in session.scalars(select(SolverState)).all()
    }
    assert all(date == second.monday_date + dt.timedelta(days=6) for _, date in newer.values()), (
        "precondition: the later week owns the boundary"
    )

    # Now swap inside the EARLIER week.
    rows = _rows(session, first)
    sunday_bagnini = [a for a in rows if a.day is Day.SUN and a.role is AssignmentRole.BAGNINO]
    mine, theirs = sorted(sunday_bagnini, key=lambda a: a.slot.value)
    requester = session.get(User, mine.user_id)
    target = session.get(User, theirs.user_id)
    assert requester is not None and target is not None

    login(client, requester.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 201, body
    login(client, target.username)
    assert client.post(f"/api/swaps/{body['id']}/accept").status_code == 200

    session.expire_all()
    after = {
        state.user_id: (state.last_worked_slot, state.last_worked_date)
        for state in session.scalars(select(SolverState)).all()
    }
    assert after == newer, "the older week's swap must not disturb the newer boundary"


def test_weekend_spiaggino_swap_is_refused(client: TestClient, session: DbSession) -> None:
    """§2.1 H5: any weekend swap with a spiaggino side is refused — the two
    full-day spiaggini are the template's fixed point."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    weekend_spiaggini = [
        a for a in rows if a.day in _WEEKEND and a.role is AssignmentRole.SPIAGGINO
    ]
    assert weekend_spiaggini, "H5 puts two spiaggini on every weekend slot"
    mine = weekend_spiaggini[0]
    theirs = next(
        a
        for a in weekend_spiaggini
        if a.user_id != mine.user_id and a.day is mine.day and a.slot is mine.slot
    )
    requester = session.get(User, mine.user_id)
    target = session.get(User, theirs.user_id)
    assert requester is not None and target is not None

    login(client, requester.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 422, body
    assert body["detail"] == "swap_weekend_bagnini_only"


# --- the §4 state machine ----------------------------------------------------


def _pending_swap(client: TestClient, session: DbSession, roster: dict[str, User]) -> dict:
    """A real pending swap between two core bagnini, created over HTTP."""
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    mine, theirs = _find_same_day_pair(rows, roster, AssignmentRole.BAGNINO)
    requester = session.get(User, mine.user_id)
    target = session.get(User, theirs.user_id)
    assert requester is not None and target is not None
    login(client, requester.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 201, body
    return {
        "id": body["id"],
        "requester": requester,
        "target": target,
        "mine": mine,
        "theirs": theirs,
        "week": week,
    }


def test_only_the_addressed_worker_may_answer(client: TestClient, session: DbSession) -> None:
    """§4: B accepts or rejects — the requester cannot answer their own request,
    and an uninvolved worker is not even told the swap exists."""
    roster = create_full_roster(session)
    swap = _pending_swap(client, session, roster)

    # The requester: involved, so 403 rather than a misleading 404.
    login(client, swap["requester"].username)
    resp = client.post(f"/api/swaps/{swap['id']}/accept")
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "swap_wrong_target"

    # A third party: not their business at all — uniform 404, no existence leak.
    outsider = next(
        u for u in roster.values() if u.id not in (swap["requester"].id, swap["target"].id)
    )
    login(client, outsider.username)
    resp = client.post(f"/api/swaps/{swap['id']}/accept")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "swap_not_found"

    # Control: the addressed worker CAN act, so the refusals above are about
    # authority, not about a broken endpoint.
    login(client, swap["target"].username)
    assert client.post(f"/api/swaps/{swap['id']}/accept").status_code == 200


def test_a_resolved_swap_cannot_be_answered_twice(client: TestClient, session: DbSession) -> None:
    """§4: the state machine is one-way — an applied request is closed."""
    roster = create_full_roster(session)
    swap = _pending_swap(client, session, roster)
    login(client, swap["target"].username)
    assert client.post(f"/api/swaps/{swap['id']}/accept").status_code == 200

    resp = client.post(f"/api/swaps/{swap['id']}/accept")
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "swap_already_resolved"
    assert len(_audit_rows(session, "apply")) == 1, "the second accept applied nothing"


def test_reject_closes_the_request_and_tells_the_requester(
    client: TestClient, session: DbSession
) -> None:
    """§4: B rejects → the request expires unfulfilled and the schedule stands."""
    roster = create_full_roster(session)
    swap = _pending_swap(client, session, roster)
    login(client, swap["target"].username)
    resp = client.post(f"/api/swaps/{swap['id']}/reject")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"

    session.expire_all()
    row = session.get(SwapRequest, swap["id"])
    assert row is not None and row.status is SwapStatus.REJECTED
    assert row.resolved_at is not None
    assert session.get(Assignment, swap["mine"].id).user_id == swap["requester"].id
    assert [n.user_id for n in _notes(session, EVENT_SWAP_REJECTED)] == [swap["requester"].id]


def test_a_swap_on_an_unlocked_week_is_refused(client: TestClient, session: DbSession) -> None:
    """§3.4: swaps are the POST-lock instrument. Before publish the schedule is
    not even visible, let alone tradeable."""
    roster = create_full_roster(session)
    monday = _future_monday()
    week = get_or_create_week(session, monday)
    run_solve(session, week)  # solved, NOT published
    session.refresh(week)
    assert week.status is WeekStatus.SOLVED
    rows = _rows(session, week)
    mine, theirs = _find_same_day_pair(rows, roster, AssignmentRole.BAGNINO)
    requester = session.get(User, mine.user_id)
    target = session.get(User, theirs.user_id)
    assert requester is not None and target is not None

    login(client, requester.username)
    code, body = _create(client, target, mine, theirs)
    assert code == 409, body
    assert body["detail"] == "week_not_locked"


def test_a_worker_cannot_swap_with_themselves(client: TestClient, session: DbSession) -> None:
    """§4: a swap is a trade between two people."""
    roster = create_full_roster(session)
    week = _published_week(session, roster, _future_monday())
    rows = _rows(session, week)
    matteo = roster["matteo"]
    own = [a for a in rows if a.user_id == matteo.id]
    assert len(own) >= 2

    login(client, matteo.username)
    code, body = _create(client, matteo, own[0], own[1])
    assert code == 422, body
    assert body["detail"] == "swap_self"


# --- REQUIRE_ADMIN_APPROVAL: built now, shipped off (§4, §13) ----------------


def test_admin_approval_flag_parks_the_swap_without_applying(
    client: TestClient, session: DbSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§4: with the flag ON an accepted swap enters `pending_admin` BEFORE
    applying — the schedule is untouched until an admin approves. The approval
    surface itself is deferred (§13); the state machine is what ships."""
    monkeypatch.setattr(settings, "require_admin_approval", True)
    roster = create_full_roster(session)
    swap = _pending_swap(client, session, roster)

    login(client, swap["target"].username)
    resp = client.post(f"/api/swaps/{swap['id']}/accept")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending_admin"

    session.expire_all()
    # The whole point: consent was recorded, the schedule was NOT changed.
    assert session.get(Assignment, swap["mine"].id).user_id == swap["requester"].id
    assert session.get(Assignment, swap["theirs"].id).user_id == swap["target"].id
    assert session.get(Assignment, swap["mine"].id).source is not AssignmentSource.SWAP
    assert _audit_rows(session, "apply") == []
    assert _audit_rows(session, "pending_admin")


def test_the_flag_is_off_by_default(client: TestClient, session: DbSession) -> None:
    """§4/§13: "build the state machine now; ship with the flag off"."""
    assert settings.require_admin_approval is False


# --- the 48 h timeout (§4) ---------------------------------------------------


def _age_swap(session: DbSession, swap_id: int, age: dt.timedelta) -> None:
    row = session.get(SwapRequest, swap_id)
    assert row is not None
    row.created_at = row.created_at - age
    session.commit()


def test_the_scheduled_sweep_expires_a_stale_request(
    client: TestClient, session: DbSession
) -> None:
    """§4: 48 h timeout → `expired`. A system transition: NULL audit actor (§6),
    and NO notification — §10's event list names no expiry event."""
    roster = create_full_roster(session)
    swap = _pending_swap(client, session, roster)
    notes_before = len(session.scalars(select(Notification)).all())
    _age_swap(session, swap["id"], SWAP_TTL + dt.timedelta(minutes=1))

    expired = expire_stale_swaps(session, dt.datetime.now(dt.UTC))
    assert expired == 1

    session.expire_all()
    row = session.get(SwapRequest, swap["id"])
    assert row is not None and row.status is SwapStatus.EXPIRED
    assert row.resolved_at is not None
    audit = _audit_rows(session, "expire")
    assert len(audit) == 1
    assert audit[0].actor_id is None, "§6: a timeout has no human actor"
    assert len(session.scalars(select(Notification)).all()) == notes_before


def test_a_fresh_request_survives_the_sweep(client: TestClient, session: DbSession) -> None:
    """Control: the sweep expires the overdue, not the merely pending."""
    roster = create_full_roster(session)
    swap = _pending_swap(client, session, roster)
    _age_swap(session, swap["id"], SWAP_TTL - dt.timedelta(hours=1))

    assert expire_stale_swaps(session, dt.datetime.now(dt.UTC)) == 0
    session.expire_all()
    assert session.get(SwapRequest, swap["id"]).status is SwapStatus.PENDING


def test_accepting_after_48h_expires_instead_of_applying(
    client: TestClient, session: DbSession
) -> None:
    """§4: the timeout holds even if the hourly sweep has not fired yet — an
    accept at hour 49 lands on `expired`, never on a stale `pending`."""
    roster = create_full_roster(session)
    swap = _pending_swap(client, session, roster)
    _age_swap(session, swap["id"], SWAP_TTL + dt.timedelta(minutes=1))

    login(client, swap["target"].username)
    resp = client.post(f"/api/swaps/{swap['id']}/accept")
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "swap_already_resolved"

    session.expire_all()
    assert session.get(SwapRequest, swap["id"]).status is SwapStatus.EXPIRED
    assert session.get(Assignment, swap["mine"].id).user_id == swap["requester"].id
    assert _audit_rows(session, "apply") == []


def test_listing_expires_an_overdue_request(client: TestClient, session: DbSession) -> None:
    """§4: an overdue request must never RENDER as actionable, so the listing
    runs the same expiry transition the sweep does."""
    roster = create_full_roster(session)
    swap = _pending_swap(client, session, roster)
    _age_swap(session, swap["id"], SWAP_TTL + dt.timedelta(minutes=1))

    login(client, swap["target"].username)
    body = client.get("/api/swaps", params={"week": swap["week"].monday_date.isoformat()}).json()
    assert [s["status"] for s in body] == ["expired"]


# --- GET /swaps visibility ---------------------------------------------------


def test_listing_returns_only_the_callers_own_swaps(client: TestClient, session: DbSession) -> None:
    """A swap is the two parties' business: both see it, an outsider sees
    nothing. §5 grants the admin no swap-specific row, so there is deliberately
    no admin-wide listing to test."""
    roster = create_full_roster(session)
    swap = _pending_swap(client, session, roster)
    monday = swap["week"].monday_date.isoformat()

    for party in (swap["requester"], swap["target"]):
        login(client, party.username)
        body = client.get("/api/swaps", params={"week": monday}).json()
        assert [s["id"] for s in body] == [swap["id"]]

    outsider = next(
        u for u in roster.values() if u.id not in (swap["requester"].id, swap["target"].id)
    )
    login(client, outsider.username)
    assert client.get("/api/swaps", params={"week": monday}).json() == []


def test_listing_an_unknown_week_is_empty_not_an_error(
    client: TestClient, session: DbSession
) -> None:
    create_full_roster(session)
    login(client, "pasha")
    resp = client.get("/api/swaps", params={"week": _future_monday(40).isoformat()})
    assert resp.status_code == 200
    assert resp.json() == []


def test_swap_payloads_never_leak_root_or_the_feed_token(
    client: TestClient, session: DbSession
) -> None:
    """§5 (root invisible) + §6 v1.7 (ics_token is its owner's alone): the swap
    surface names users by id, and must never grow a serialized user object
    carrying either secret."""
    roster = create_full_roster(session)
    swap = _pending_swap(client, session, roster)
    login(client, swap["target"].username)
    body = client.get("/api/swaps", params={"week": swap["week"].monday_date.isoformat()}).json()
    assert body

    serialized = repr(body)
    assert "is_root" not in serialized
    assert "ics_token" not in serialized
    assert set(body[0]) == {
        "id",
        "week",
        "from_user",
        "to_user",
        "from_assignment",
        "to_assignment",
        "status",
        "created_at",
        "resolved_at",
    }
    assert set(body[0]["from_assignment"]) == {"id", "day", "slot", "role", "user_id"}
