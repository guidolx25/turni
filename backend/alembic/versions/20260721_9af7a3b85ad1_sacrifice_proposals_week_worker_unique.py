"""sacrifice_proposals: UNIQUE(week_id, user_id) — grant of record (spec v1.6)

v1.6 makes the ACCEPTED sacrifice_proposals row the §2.1 H3 grant of record:
every solve of a week reads its accepted proposals and carries their grants.
That promotes the row from a conversation artifact to a model input, so one
worker must never hold two proposals for one week — a duplicate could silently
widen the H3 domain twice. Safe by construction (§2.3 corollary: Friday is the
only reachable sacrifice day), enforced here so a logic error surfaces as an
IntegrityError instead of a wrong schedule.

If a pre-v1.6 database held duplicate (week_id, user_id) rows, this migration
fails loudly rather than guessing which row was the real conversation.

Revision ID: 9af7a3b85ad1
Revises: d459c09baf30
Create Date: 2026-07-21 00:58:54.888689

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9af7a3b85ad1"
down_revision: str | Sequence[str] | None = "d459c09baf30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Matches the metadata naming convention (uq_%(table_name)s_%(column_0_N_name)s),
# so the migrated schema and the declarative model agree on the name.
_CONSTRAINT = "uq_sacrifice_proposals_week_id_user_id"


def upgrade() -> None:
    """One proposal per (week, worker)."""
    with op.batch_alter_table("sacrifice_proposals", schema=None) as batch_op:
        batch_op.create_unique_constraint(_CONSTRAINT, ["week_id", "user_id"])


def downgrade() -> None:
    """Drop the key (rows are untouched)."""
    with op.batch_alter_table("sacrifice_proposals", schema=None) as batch_op:
        batch_op.drop_constraint(_CONSTRAINT, type_="unique")
