"""weeks.status add 'solved' state (§3 three-state lifecycle, spec v1.3)

Spec v1.3 promotes "solved but not published" from an implicit
(status=open + solved_at set) shape to an explicit third `weeks.status`
value, ordered open → solved → locked (§3, §6 weeks row).

The `week_status` enum is a VARCHAR + named CHECK constraint (native_enum=False,
create_constraint=True). Widening the allowed value set on SQLite means
rebuilding that CHECK, which `op.batch_alter_table` does by recreating the table
with the new Enum type.

Revision ID: 6d25e9d5bdf1
Revises: 19714fc7d4f1
Create Date: 2026-07-19 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6d25e9d5bdf1"
down_revision: str | Sequence[str] | None = "19714fc7d4f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Widen the week_status CHECK to include 'solved'."""
    with op.batch_alter_table("weeks", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.Enum(
                "open", "locked", name="week_status", native_enum=False, create_constraint=True
            ),
            type_=sa.Enum(
                "open",
                "solved",
                "locked",
                name="week_status",
                native_enum=False,
                create_constraint=True,
            ),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Narrow the week_status CHECK back to the 2-value set.

    Note: if any `weeks` row is in the 'solved' state at downgrade time, the
    rebuilt 2-value CHECK will reject it and the migration will fail. That is
    acceptable — 'solved' is a v1.3 state with no v1.2 representation, so a clean
    downgrade requires no week be parked in it first.
    """
    with op.batch_alter_table("weeks", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.Enum(
                "open",
                "solved",
                "locked",
                name="week_status",
                native_enum=False,
                create_constraint=True,
            ),
            type_=sa.Enum(
                "open", "locked", name="week_status", native_enum=False, create_constraint=True
            ),
            existing_nullable=False,
        )
