"""users.ics_token — per-user calendar-feed credential (spec v1.7)

§7's `GET /export/ics` is a token-authenticated URL. v1.7 gives the token a
column: per-user, random, opaque, UNIQUE. The deciding property is revocation
granularity — a leaked feed URL (the leakiest credential in the system: pasted
into calendar apps, synced to family devices) is fixed by regenerating ONE
user's token, never by rotating SECRET_KEY, which would log out every user and
kill every other feed.

Three steps because SQLite cannot add a NOT NULL column without a constant
default, and a constant would collide with UNIQUE: add nullable → backfill a
distinct random token per row → tighten to NOT NULL + UNIQUE.

Revision ID: 1c77461a3e05
Revises: 9af7a3b85ad1
Create Date: 2026-07-21 01:03:25.199173

"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1c77461a3e05"
down_revision: str | Sequence[str] | None = "9af7a3b85ad1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Matches the metadata naming convention (uq_%(table_name)s_%(column_0_N_name)s).
_CONSTRAINT = "uq_users_ics_token"


def upgrade() -> None:
    """Add, backfill (one fresh token per row), then tighten."""
    op.add_column("users", sa.Column("ics_token", sa.String(length=64), nullable=True))
    conn = op.get_bind()
    for (user_id,) in conn.execute(sa.text("SELECT id FROM users")):
        conn.execute(
            sa.text("UPDATE users SET ics_token = :token WHERE id = :id"),
            {"token": secrets.token_urlsafe(32), "id": user_id},
        )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("ics_token", existing_type=sa.String(length=64), nullable=False)
        batch_op.create_unique_constraint(_CONSTRAINT, ["ics_token"])


def downgrade() -> None:
    """Drop the credential column (feeds are dead until re-upgraded)."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint(_CONSTRAINT, type_="unique")
        batch_op.drop_column("ics_token")
