"""sacrifice_proposals: conflict_note TEXT → conflict JSON (spec v1.5)

Pre-v1.5 the column persisted a pre-formatted ENGLISH sentence, surfaced to the
target worker via the API — un-localizable after the fact (§9). v1.5 stores the
§8 minimal unsat core as data ([{worker_id, day, slot}, ...]); rendering in the
viewer's language is the §9 dictionaries' job.

Pre-existing English rows cannot be parsed back into structure, so their note is
dropped with the column. That loss was priced in when the carry-forward was
recorded: rows written before the fix bake in English the dictionaries cannot
retroactively localize.

Revision ID: d459c09baf30
Revises: 6d25e9d5bdf1
Create Date: 2026-07-21 00:54:01.497281

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d459c09baf30"
down_revision: str | Sequence[str] | None = "6d25e9d5bdf1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace the prose column with the structured core."""
    with op.batch_alter_table("sacrifice_proposals", schema=None) as batch_op:
        batch_op.drop_column("conflict_note")
        batch_op.add_column(sa.Column("conflict", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Restore the prose column (empty: structure was never a sentence)."""
    with op.batch_alter_table("sacrifice_proposals", schema=None) as batch_op:
        batch_op.drop_column("conflict")
        batch_op.add_column(sa.Column("conflict_note", sa.Text(), nullable=True))
