"""Schedule read route (spec §7 `GET /schedule`, lifecycle §3.3).

A week's schedule "becomes visible to all" only when it is published — i.e.
`locked` (§3.3). A `solved` week (window closed, schedule computed but not yet
published, §3.2) is deliberately worker-invisible: visibility keys off `locked`,
never `solved`. Before publish an admin may preview the solved grid, but an
ordinary worker sees nothing for that week yet. That visibility rule lives here;
the assignment rows themselves are produced by the solve adapter (§8).

The response names workers (including root, who works — §5 hides the root *role*,
not the roster), so it goes through `ScheduleAssignmentOut`, which structurally
omits `is_root`.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import CurrentWorker, DbDep
from app.enums import Day, WeekStatus
from app.models import Assignment, Week
from app.permissions import has_admin_capability
from app.schemas import ScheduleAssignmentOut, ScheduleOut

router = APIRouter(tags=["schedule"])

# Calendar order mon..sun for a stable, human-sensible grid (enum *values* sort
# alphabetically, which would interleave the days).
_DAY_ORDER: dict[Day, int] = {d: i for i, d in enumerate(Day)}


@router.get("/schedule", response_model=ScheduleOut)
def get_schedule(week: dt.date, worker: CurrentWorker, db: DbDep) -> ScheduleOut:
    """§7: the week's worked slots (weekday solver rows + weekend template).

    Visibility (§3.3): a `locked` week is visible to everyone; an `open` or
    `solved` week is visible only to admins (preview) — visibility keys off
    `locked`, never `solved`. A worker querying an unpublished or unknown week gets
    an empty schedule, not a leak of the draft.
    """
    week_row = db.scalar(select(Week).where(Week.monday_date == week))
    if week_row is None:
        return ScheduleOut(monday_date=week, status=WeekStatus.OPEN, assignments=[])

    visible = week_row.status is WeekStatus.LOCKED or has_admin_capability(worker)
    if not visible:
        return ScheduleOut(monday_date=week, status=week_row.status, assignments=[])

    rows = db.scalars(select(Assignment).where(Assignment.week_id == week_row.id)).all()
    ordered = sorted(rows, key=lambda a: (_DAY_ORDER[a.day], a.slot.value, a.role.value))
    return ScheduleOut(
        monday_date=week_row.monday_date,
        status=week_row.status,
        assignments=[ScheduleAssignmentOut.from_model(a) for a in ordered],
    )
