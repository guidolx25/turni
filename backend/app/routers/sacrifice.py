"""Sacrifice-proposal accept/decline routes (spec §2.3, §7 `/sacrifice/*`).

Only the proposal's *target worker* may act on it — the offer is theirs to accept
or decline (§2.3). Another user's (or an unknown) proposal is a 404, never a leak
of its existence; an already-resolved one is a 409. The re-solve/escalate logic
lives in `app.sacrifice_service`; these handlers only resolve ownership and shape.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentWorker, DbDep
from app.models import SacrificeProposal, User
from app.sacrifice_service import (
    ERROR_PROPOSAL_NOT_FOUND,
    accept_sacrifice,
    decline_sacrifice,
)
from app.schemas import SacrificeProposalOut

router = APIRouter(prefix="/sacrifice", tags=["sacrifice"])


@router.post("/{proposal_id}/accept", response_model=SacrificeProposalOut)
def accept(proposal_id: int, worker: CurrentWorker, db: DbDep) -> SacrificeProposalOut:
    """§2.3: accept the offered free day → re-solve (pinned) and publish."""
    proposal = _own_proposal(db, proposal_id, worker)
    return SacrificeProposalOut.from_model(accept_sacrifice(db, proposal, worker))


@router.post("/{proposal_id}/decline", response_model=SacrificeProposalOut)
def decline(proposal_id: int, worker: CurrentWorker, db: DbDep) -> SacrificeProposalOut:
    """§2.3: decline → escalate the unresolved conflict to the admin."""
    proposal = _own_proposal(db, proposal_id, worker)
    return SacrificeProposalOut.from_model(decline_sacrifice(db, proposal, worker))


def _own_proposal(db: DbDep, proposal_id: int, worker: User) -> SacrificeProposal:
    """The caller's own proposal, or 404 — never another worker's (no existence
    leak, and no acting on an offer that was not made to you)."""
    proposal = db.get(SacrificeProposal, proposal_id)
    if proposal is None or proposal.user_id != worker.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROPOSAL_NOT_FOUND)
    return proposal
