"""Swap routes (spec §4, §7 `/swaps`).

These handlers resolve ownership and shape only; the §4 state machine, the
shared creation/acceptance validation and the atomic application live in
`app.swap_service`.

Visibility: a swap is the two parties' business. `GET /swaps` returns only the
caller's own requests (as requester or target); acting on a swap that is not
yours — or does not exist — is a uniform 404, never an existence leak. §5 gives
the admin no swap-specific capability row, so there is deliberately no
admin-wide listing here.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select

from app.db import utcnow
from app.deps import CurrentWorker, DbDep
from app.models import SwapRequest, User, Week
from app.schemas import SwapCreateIn, SwapRequestOut
from app.swap_service import (
    ERROR_SWAP_NOT_FOUND,
    ERROR_SWAP_WRONG_TARGET,
    SwapSpec,
    accept_swap,
    create_swap,
    expire_swap,
    is_stale,
    reject_swap,
)

router = APIRouter(prefix="/swaps", tags=["swaps"])


@router.post("", response_model=SwapRequestOut, status_code=status.HTTP_201_CREATED)
def request_swap(body: SwapCreateIn, worker: CurrentWorker, db: DbDep) -> SwapRequestOut:
    """§4: propose trading one of the caller's locked slots with another worker's.
    Fully validated server-side at creation (and again at acceptance)."""
    spec = SwapSpec(
        from_user=worker.id,
        to_user=body.to_user,
        from_assignment=body.from_assignment,
        to_assignment=body.to_assignment,
    )
    return SwapRequestOut.from_model(create_swap(db, worker, spec))


@router.post("/{swap_id}/accept", response_model=SwapRequestOut)
def accept(swap_id: int, worker: CurrentWorker, db: DbDep) -> SwapRequestOut:
    """§4: only the addressed `to_user` may accept. Re-validates in full, then
    applies atomically (or parks in `pending_admin` when the §4 flag is on)."""
    swap = _addressed_swap(db, swap_id, worker)
    return SwapRequestOut.from_model(accept_swap(db, swap, worker))


@router.post("/{swap_id}/reject", response_model=SwapRequestOut)
def reject(swap_id: int, worker: CurrentWorker, db: DbDep) -> SwapRequestOut:
    """§4: only the addressed `to_user` may reject."""
    swap = _addressed_swap(db, swap_id, worker)
    return SwapRequestOut.from_model(reject_swap(db, swap, worker))


@router.get("", response_model=list[SwapRequestOut])
def list_swaps(week: dt.date, worker: CurrentWorker, db: DbDep) -> list[SwapRequestOut]:
    """§7 `GET /swaps?week=`: the caller's own swaps for that week — as requester
    or as target. An unknown week is an empty list, not an error."""
    week_row = db.scalar(select(Week).where(Week.monday_date == week))
    if week_row is None:
        return []
    swaps = db.scalars(
        select(SwapRequest)
        .where(
            SwapRequest.week_id == week_row.id,
            or_(SwapRequest.from_user == worker.id, SwapRequest.to_user == worker.id),
        )
        .order_by(SwapRequest.created_at.desc(), SwapRequest.id.desc())
    ).all()
    # Lazy half of the §4 48 h expiry: never render an overdue request as still
    # `pending` (and thus actionable) just because the hourly sweep has not
    # fired yet — same `expire_swap` transition the sweep uses, audit included.
    now = utcnow()
    expired_any = False
    for swap in swaps:
        if is_stale(swap, now):
            expire_swap(db, swap, now)
            expired_any = True
    if expired_any:
        db.commit()
    return [SwapRequestOut.from_model(swap) for swap in swaps]


def _addressed_swap(db: DbDep, swap_id: int, worker: User) -> SwapRequest:
    """The swap `worker` may act on. A swap that does not exist or does not
    involve the caller at all is a uniform 404 (no existence leak); a swap the
    caller requested — rather than received — is a 403: only the addressed
    `to_user` accepts or rejects (§4)."""
    swap = db.get(SwapRequest, swap_id)
    if swap is None or worker.id not in (swap.from_user, swap.to_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_SWAP_NOT_FOUND)
    if worker.id != swap.to_user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_SWAP_WRONG_TARGET)
    return swap
