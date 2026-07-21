"""Full simulated week (spec §12 Phase 3 gate) — submissions → the week's ending.

The headline gate scenario, driven end-to-end through the HTTP API the way the
real lifecycle runs. A week has three possible endings, and all three are
simulated here:

A. **Feasible → published.** Workers submit, the admin solves, publishes, the
   locked schedule is readable by everyone and the submission window is shut.
B. **Forced infeasibility → §2.3 conversation → accept → published, driven by a
   REAL `/admin/solve`.** The Phase 3 gate's sacrifice criterion: a hard Friday
   request makes the solve INFEASIBLE, the §2.3 probe carrying a Friday sacrifice
   grant succeeds, a proposal is opened, the worker accepts over HTTP, the week
   re-solves and publishes — with the hard request honored in full.
   (`test_full_week_real_sacrifice_propose_accept_resolve`.)
C. **Forced infeasibility whose extended probe also fails → admin escalation.**
   A Friday conflict compounded so that even the Friday-extended probe cannot
   meet coverage: §2.3 step 3 applies, no proposal is opened, the visible admin is
   escalated to and the week stays parked in `solved`, publishable by nobody.

B′ (`test_full_week_sacrifice_accepted_leads_to_publish`) is retained as
DOWNSTREAM coverage of the accept→re-solve→publish machinery on a plain feasible
week, with the proposal seeded directly. It deliberately does not stand in for
scenario B: only B exercises the propose branch from a real solve.

The solver's own correctness has unit coverage (`tests/solver/`, in particular
`test_sacrifice_grant.py` for the H3 domain extension); here the point is that the
*lifecycle wiring* holds together.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.enums import Day, SacrificeStatus, WeekStatus
from app.models import AuditLog, Notification, SacrificeProposal, SolverState, Week
from app.notifications import EVENT_SACRIFICE_ESCALATED
from app.sacrifice_service import _create_proposal
from app.scheduling import get_or_create_week
from tests.factories import PASSWORD, create_full_roster

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase3


def _future_monday(weeks_ahead: int = 2) -> dt.date:
    today = dt.datetime.now(dt.UTC).date()
    next_monday = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)
    return next_monday + dt.timedelta(weeks=weeks_ahead - 1)


def login(client: TestClient, username: str) -> None:
    resp = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


def _submit(client: TestClient, monday: dt.date, day: str, slot: str, kind: str) -> None:
    resp = client.post(
        "/api/constraints",
        json={"week": monday.isoformat(), "day": day, "slot": slot, "kind": kind},
    )
    assert resp.status_code == 201, resp.text


def _submit_the_week(client: TestClient, monday: dt.date) -> None:
    """The roster's soft rest preferences for the week (§3.1 submission window).

    Every request is inside the requester's §2.1 H3(b) ROLE domain — spiaggini
    {Mon, Tue}, bagnini {Tue, Wed} — so the set is jointly satisfiable and the
    simulation tests the lifecycle rather than an unsatisfiable week. Amir asked
    for Wednesday before v1.12; as a spiaggino he now cannot have it at any
    strength, which made `soft_unmet == 0` unreachable by construction. That
    silent-drop behaviour is real and is covered on its own below, rather than by
    weakening this scenario's assertion.
    """
    login(client, "francesco")
    _submit(client, monday, "tue", "full_day", "soft")  # bagnino: prefers Tuesday off
    login(client, "amir")
    _submit(client, monday, "tue", "full_day", "soft")  # spiaggino: prefers Tuesday off
    login(client, "pasha")
    _submit(client, monday, "mon", "full_day", "soft")  # spiaggino: prefers Monday off


def _assert_h1_weekday_coverage(assignments: list[dict]) -> None:
    """H1: every Mon–Fri slot has exactly one bagnino and exactly one spiaggino."""
    for day in ("mon", "tue", "wed", "thu", "fri"):
        for slot in ("am", "pm"):
            holders = [a for a in assignments if a["day"] == day and a["slot"] == slot]
            roles = sorted(a["role"] for a in holders)
            assert roles == ["bagnino", "spiaggino"], f"{day}/{slot}: {roles}"


def _assert_published_week_is_sound(
    client: TestClient, session: DbSession, monday: dt.date
) -> None:
    """The invariants every published week must satisfy, whatever route it took:
    LOCKED, readable by a plain worker, H1-covered, window shut, solver_state
    seeded for next week's §2.2 boundary, and the publish audited."""
    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.LOCKED

    login(client, "amir")  # an uninvolved worker
    feed = client.get("/api/notifications").json()
    assert any(n["event_type"] == "schedule_published" for n in feed)
    grid = client.get("/api/schedule", params={"week": monday.isoformat()}).json()
    assert grid["status"] == "locked"
    _assert_h1_weekday_coverage(grid["assignments"])

    # §3.1/§3.4: the window is shut — a post-lock submission is refused.
    login(client, "pasha")
    assert (
        client.post(
            "/api/constraints",
            json={"week": monday.isoformat(), "day": "mon", "slot": "am", "kind": "hard"},
        ).status_code
        == 409  # week_closed
    )
    assert session.scalars(select(SolverState)).all()  # next-week boundary written
    assert session.scalars(select(AuditLog).where(AuditLog.action == "publish")).all()


# --- A. the feasible week ---------------------------------------------------


def test_full_week_submissions_to_publish(client: TestClient, session: DbSession) -> None:
    """§3.1→§3.4: submissions → solve → publish → locked, readable, window shut."""
    create_full_roster(session)
    monday = _future_monday()

    _submit_the_week(client, monday)

    # The week is materialised, open, with submissions visible to their owner.
    weeks = client.get("/api/weeks").json()
    assert any(w["monday_date"] == monday.isoformat() and w["status"] == "open" for w in weeks)
    assert len(client.get("/api/constraints", params={"week": monday.isoformat()}).json()) == 1

    login(client, "mattia")
    solve = client.post("/api/admin/solve", params={"week": monday.isoformat()})
    assert solve.status_code == 200, solve.text
    assert solve.json()["status"] in ("optimal", "feasible")
    # §2.2 S1: the three soft rest requests are jointly satisfiable this week.
    assert solve.json()["objective"]["soft_unmet"] == 0

    assert client.post("/api/admin/publish", params={"week": monday.isoformat()}).status_code == 200
    _assert_published_week_is_sound(client, session, monday)


# --- B. the real §2.3 path: solve → probe → propose → accept → publish ------


def test_full_week_real_sacrifice_propose_accept_resolve(
    client: TestClient, session: DbSession
) -> None:
    """§2.3 end to end from a REAL `/admin/solve`, nothing seeded (Phase 3 gate).

    Pasha submits a hard full-day FRIDAY request. Friday is the one day H4 forces
    worked that his spiaggino role domain {Mon, Tue} cannot free (§2.3's
    reachable-days table), so the solve is INFEASIBLE and the §8 unsat core names
    him. The flow probes with a Friday **sacrifice grant** (`{Mon, Tue} ∪ {Fri}`)
    plus the matching pin, finds it feasible, and opens a PENDING proposal offering
    Friday. Pasha accepts over HTTP; the week re-solves carrying the grant and
    publishes.

    The trade asserted here is exactly the one §2.3 defines: he gives up his
    *weekday free-day placement* — he works all four other weekdays — and his hard
    request is honored IN FULL, zero Friday slots, with the jolly covering the
    Friday slot he vacated. H7 is never downgraded to buy the resolution.
    """
    roster = create_full_roster(session)
    monday = _future_monday()

    _submit_the_week(client, monday)
    login(client, "pasha")
    _submit(client, monday, "fri", "full_day", "hard")

    # 1. Solve → INFEASIBLE, and the core names the worker who blocks it (§8).
    login(client, "mattia")
    solve = client.post("/api/admin/solve", params={"week": monday.isoformat()})
    assert solve.status_code == 200, solve.text
    assert solve.json()["status"] == "infeasible"
    assert any(
        b["worker_id"] == roster["pasha"].id and b["day"] == "fri"
        for b in solve.json()["blocking_constraints"]
    ), solve.json()["blocking_constraints"]

    # 2. The probe succeeded → exactly one PENDING proposal, to him, offering Fri.
    proposals = session.scalars(select(SacrificeProposal)).all()
    assert len(proposals) == 1
    assert proposals[0].user_id == roster["pasha"].id
    assert proposals[0].status is SacrificeStatus.PENDING
    assert proposals[0].proposed_free_day is Day.FRI

    # 3. He reads the offer off his own notifications and accepts it over HTTP.
    login(client, "pasha")
    notes = client.get("/api/notifications").json()
    proposed = next(n for n in notes if n["event_type"] == "sacrifice_proposed")
    assert proposed["payload"]["proposed_free_day"] == "fri"
    accept = client.post(f"/api/sacrifice/{proposed['payload']['proposal_id']}/accept")
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == "accepted"

    # 4. The re-solve was feasible and the week published — the whole gate path.
    _assert_published_week_is_sound(client, session, monday)

    login(client, "pasha")
    grid = client.get("/api/schedule", params={"week": monday.isoformat()}).json()
    mine = [a for a in grid["assignments"] if a["user_id"] == roster["pasha"].id]

    # H7 in full: ZERO Friday slots. This is the whole point of the trade.
    assert [a for a in mine if a["day"] == "fri"] == []
    # The sacrifice: his free day IS Friday, so he works all four other weekdays,
    # one slot each (H4) — the weekday rest he would otherwise have taken is gone.
    for day in ("mon", "tue", "wed", "thu"):
        assert len([a for a in mine if a["day"] == day]) == 1, f"{day} must be worked"

    # H6/H1: the jolly absorbs the Friday slot he vacated; coverage still holds.
    friday_spiaggini = [
        a for a in grid["assignments"] if a["day"] == "fri" and a["role"] == "spiaggino"
    ]
    assert len(friday_spiaggini) == 2
    assert any(a["user_id"] == roster["mattia"].id for a in friday_spiaggini)

    # §10: he is told the outcome, naming the day he took as rest instead.
    resolved = next(
        n
        for n in client.get("/api/notifications").json()
        if n["event_type"] == "sacrifice_resolved"
    )
    assert resolved["payload"]["free_day"] == "fri"


# --- B′. downstream: accept → re-solve → publish (seeded proposal) ----------


def test_full_week_sacrifice_accepted_leads_to_publish(
    client: TestClient, session: DbSession
) -> None:
    """§2.3 steps 2–3 downstream machinery, on a plain feasible week with the
    proposal seeded: the offered worker reads it off their own notifications,
    accepts over HTTP, and the week re-solves with the accepted free day PINNED
    and publishes. The pin is honored in the published grid.

    Not the gate's propose→accept→re-solve criterion — that is scenario B above,
    which drives the same machinery from a real INFEASIBLE `/admin/solve`."""
    roster = create_full_roster(session)
    monday = _future_monday()

    _submit_the_week(client, monday)

    login(client, "mattia")
    assert client.post("/api/admin/solve", params={"week": monday.isoformat()}).status_code == 200

    # The §2.3 conversation is opened with Pasha (see module docstring on seeding).
    week = get_or_create_week(session, monday)
    _create_proposal(
        session,
        week,
        roster["pasha"].id,
        Day.THU,
        conflict=[{"worker_id": roster["pasha"].id, "day": "thu", "slot": "full_day"}],
    )

    # While the offer is open the week cannot be published (§3.3).
    login(client, "mattia")
    blocked = client.post("/api/admin/publish", params={"week": monday.isoformat()})
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "sacrifice_pending"

    # Pasha reads the offer off his notifications and accepts it.
    login(client, "pasha")
    notes = client.get("/api/notifications").json()
    proposed = next(n for n in notes if n["event_type"] == "sacrifice_proposed")
    assert proposed["payload"]["proposed_free_day"] == "thu"
    accept = client.post(f"/api/sacrifice/{proposed['payload']['proposal_id']}/accept")
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == "accepted"

    _assert_published_week_is_sound(client, session, monday)

    # The sacrifice he made is honored: zero Thursday slots, and H3 still holds
    # (his free day MOVED to Thursday — Friday is worked, never rested).
    login(client, "pasha")
    grid = client.get("/api/schedule", params={"week": monday.isoformat()}).json()
    mine = [a for a in grid["assignments"] if a["user_id"] == roster["pasha"].id]
    assert [a for a in mine if a["day"] == "thu"] == []
    assert [a for a in mine if a["day"] == "fri"], "H3: Friday is always worked"


# --- D. the v1.12 silent drop: a SOFT out-of-domain request -----------------


def test_soft_out_of_domain_request_is_dropped_silently_with_no_proposal(
    client: TestClient, session: DbSession
) -> None:
    """§2.1 H3(b) + §2.2 S1 (v1.12): a SOFT full-day request on a day outside the
    requester's role domain is UNSATISFIABLE by construction — the free day cannot
    move there without a §2.3 grant, and §2.3 issues grants only for HARD
    constraints. So the week solves, the request comes back counted unmet, and
    nothing else happens: no sacrifice proposal, no escalation, no notification.

    A new consequence of the v1.12 domains, and one worth pinning precisely because
    it is silent: before v1.12 a Wednesday request from a spiaggino was ordinary
    and satisfiable. The contrast with the HARD version of the same request — which
    makes the week INFEASIBLE and opens the §2.3 conversation — is asserted in the
    same test so the two paths cannot drift into each other.
    """
    roster = create_full_roster(session)
    monday = _future_monday()

    # Amir is a spiaggino (domain {Mon, Tue}); Wednesday is outside it.
    login(client, "amir")
    _submit(client, monday, "wed", "full_day", "soft")

    login(client, "mattia")
    solve = client.post("/api/admin/solve", params={"week": monday.isoformat()})
    assert solve.status_code == 200, solve.text
    # The week still SOLVES — a soft request never blocks anything (§2.2).
    assert solve.json()["status"] in ("optimal", "feasible")
    # ... and the request is simply counted unmet.
    assert solve.json()["objective"]["soft_unmet"] == 1

    # Silent: §2.3 is a HARD-constraint flow, so nothing was offered or escalated.
    assert session.scalars(select(SacrificeProposal)).all() == []
    login(client, "amir")
    events = {n["event_type"] for n in client.get("/api/notifications").json()}
    assert not events & {"sacrifice_proposed", "sacrifice_resolved", EVENT_SACRIFICE_ESCALATED}

    # His free day landed inside his role domain, and Wednesday is worked.
    login(client, "mattia")
    assert client.post("/api/admin/publish", params={"week": monday.isoformat()}).status_code == 200
    grid = client.get("/api/schedule", params={"week": monday.isoformat()}).json()
    mine = [a for a in grid["assignments"] if a["user_id"] == roster["amir"].id]
    assert [a for a in mine if a["day"] == "wed"], "H3(b): a spiaggino always works Wednesday"
    assert {a["day"] for a in mine} & {"mon", "tue"} != {"mon", "tue"}, (
        "H3(a): exactly one of his two in-domain days is free"
    )


def test_the_same_request_submitted_hard_does_open_the_conversation(
    client: TestClient, session: DbSession
) -> None:
    """The control for the silent drop above: SAME worker, SAME day, kind=HARD.
    Wednesday is `reachable` for a spiaggino (§2.3 table), so the week is
    INFEASIBLE, the probe carrying a Wednesday grant succeeds, and a proposal IS
    opened. The difference between the two outcomes is the constraint's kind and
    nothing else."""
    roster = create_full_roster(session)
    monday = _future_monday()

    login(client, "amir")
    _submit(client, monday, "wed", "full_day", "hard")

    login(client, "mattia")
    solve = client.post("/api/admin/solve", params={"week": monday.isoformat()})
    assert solve.status_code == 200, solve.text
    assert solve.json()["status"] == "infeasible"

    proposals = session.scalars(select(SacrificeProposal)).all()
    assert len(proposals) == 1
    assert proposals[0].user_id == roster["amir"].id
    assert proposals[0].proposed_free_day is Day.WED
    assert proposals[0].status is SacrificeStatus.PENDING


# --- C. infeasibility the extended probe cannot fix → admin escalation ------


def test_full_week_friday_conflict_with_infeasible_probe_ends_in_admin_escalation(
    client: TestClient, session: DbSession
) -> None:
    """§2.3 step 3: "a Friday conflict whose extended probe is *still* infeasible
    produces no proposal and escalates". The counter-case to scenario B, and the
    third possible ending of a week.

    Compounded so the probe genuinely fails on COVERAGE, not incidentally: Pasha is
    hard-off Friday AND the jolly is hard-off Friday. Granting Pasha a Friday free
    day would leave Friday needing two spiaggino slots with only Amir available,
    and H4 gives him exactly one — H1 cannot be met, so the extended probe is
    INFEASIBLE. Scenario B is the same fixture WITHOUT the jolly's request and does
    open a proposal, which is what pins the cause on the added conflict.

    The week's lifecycle therefore ends in an admin escalation, not a publish: no
    proposal is opened, nothing is published, the week stays parked in `solved`,
    and the visible admin — never root — holds the conflict.
    """
    roster = create_full_roster(session)
    monday = _future_monday()

    _submit_the_week(client, monday)
    login(client, "pasha")
    _submit(client, monday, "fri", "full_day", "hard")  # HARD Friday off → infeasible
    login(client, "mattia")
    _submit(client, monday, "fri", "full_day", "hard")  # and the jolly cannot cover it

    login(client, "mattia")
    solve = client.post("/api/admin/solve", params={"week": monday.isoformat()})
    assert solve.status_code == 200, solve.text
    assert solve.json()["status"] == "infeasible"
    assert solve.json()["blocking_constraints"], "§8: the core must name the conflict"

    # No proposal at all: the Friday-extended probe failed, so the branch never
    # fired. (A Friday free day is LEGAL under a §2.3 grant — what is absent
    # here is the offer, not an "illegal" day.)
    assert session.scalars(select(SacrificeProposal)).all() == []

    # The visible admin holds the conflict, with the explanation; root does not.
    escalations = session.scalars(
        select(Notification).where(Notification.event_type == EVENT_SACRIFICE_ESCALATED)
    ).all()
    assert [n.user_id for n in escalations] == [roster["mattia"].id]
    core = escalations[0].payload["conflict"]
    assert any(item["worker_id"] == roster["pasha"].id and item["day"] == "fri" for item in core), (
        f"the structured core must implicate Pasha's Friday request: {core}"
    )

    # Nothing was published, and the admin cannot publish the conflict away.
    assert (
        session.scalars(
            select(Notification).where(Notification.event_type == "schedule_published")
        ).all()
        == []
    )
    assert client.post("/api/admin/publish", params={"week": monday.isoformat()}).status_code == 409

    session.expire_all()
    week = session.scalar(select(Week).where(Week.monday_date == monday))
    assert week is not None and week.status is WeekStatus.SOLVED  # parked for the admin

    # The worker sees no schedule and was told nothing was resolved on his behalf.
    login(client, "pasha")
    grid = client.get("/api/schedule", params={"week": monday.isoformat()}).json()
    assert grid["assignments"] == []
    assert not any(
        n["event_type"] in ("sacrifice_proposed", "sacrifice_resolved")
        for n in client.get("/api/notifications").json()
    )
