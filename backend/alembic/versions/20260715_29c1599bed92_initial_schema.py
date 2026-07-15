"""initial schema

The ten tables of spec §6, verbatim.

Enums are VARCHAR + named CHECK rather than a native type: SQLite has no ENUM.
Every constraint is named via the MetaData naming convention so that later
migrations can rebuild these tables in batch mode.

Revision ID: 29c1599bed92
Revises:
Create Date: 2026-07-15 20:21:52.374891

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "29c1599bed92"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the §6 schema."""
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('display_name', sa.String(length=128), nullable=False),
    sa.Column('role', sa.Enum('bagnino', 'spiaggino', 'jolly', name='user_role', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('is_admin', sa.Boolean(), nullable=False),
    sa.Column('is_root', sa.Boolean(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('email_notifications', sa.Boolean(), nullable=False),
    sa.Column('language', sa.Enum('it', 'en', name='language', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('username', name=op.f('uq_users_username'))
    )
    op.create_table('weeks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('monday_date', sa.Date(), nullable=False),
    sa.Column('status', sa.Enum('open', 'locked', name='week_status', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('solved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_weeks')),
    sa.UniqueConstraint('monday_date', name=op.f('uq_weeks_monday_date'))
    )
    op.create_table('assignments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('week_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.Enum('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', name='day', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('slot', sa.Enum('am', 'pm', name='assignment_slot', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('role', sa.Enum('bagnino', 'spiaggino', name='assignment_role', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.Enum('solver', 'weekend_template', 'swap', 'override', name='assignment_source', native_enum=False, create_constraint=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_assignments_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['week_id'], ['weeks.id'], name=op.f('fk_assignments_week_id_weeks'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assignments')),
    sa.UniqueConstraint('week_id', 'day', 'slot', 'role', name=op.f('uq_assignments_week_id_day_slot_role'))
    )
    with op.batch_alter_table('assignments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_assignments_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_assignments_week_id'), ['week_id'], unique=False)

    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('entity', sa.String(length=64), nullable=False),
    sa.Column('entity_id', sa.Integer(), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_audit_log_actor_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_log_actor_id'), ['actor_id'], unique=False)

    op.create_table('constraints',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('week_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.Enum('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', name='day', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('slot', sa.Enum('am', 'pm', 'full_day', name='constraint_slot', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('kind', sa.Enum('hard', 'soft', name='constraint_kind', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_constraints_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['week_id'], ['weeks.id'], name=op.f('fk_constraints_week_id_weeks'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_constraints')),
    sa.UniqueConstraint('user_id', 'week_id', 'day', 'slot', name=op.f('uq_constraints_user_id_week_id_day_slot'))
    )
    with op.batch_alter_table('constraints', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_constraints_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_constraints_week_id'), ['week_id'], unique=False)

    op.create_table('notifications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('read', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications'))
    )
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notifications_user_id'), ['user_id'], unique=False)

    op.create_table('sacrifice_proposals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('week_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('proposed_free_day', sa.Enum('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', name='day', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('status', sa.Enum('pending', 'accepted', 'declined', name='sacrifice_status', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('conflict_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sacrifice_proposals_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['week_id'], ['weeks.id'], name=op.f('fk_sacrifice_proposals_week_id_weeks'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sacrifice_proposals'))
    )
    with op.batch_alter_table('sacrifice_proposals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sacrifice_proposals_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_sacrifice_proposals_week_id'), ['week_id'], unique=False)

    op.create_table('sessions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions'))
    )
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_sessions_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('solver_state',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('last_worked_slot', sa.Enum('am', 'pm', name='assignment_slot', native_enum=False, create_constraint=True), nullable=True),
    sa.Column('last_worked_date', sa.Date(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_solver_state_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_solver_state'))
    )
    op.create_table('swap_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('week_id', sa.Integer(), nullable=False),
    sa.Column('from_user', sa.Integer(), nullable=False),
    sa.Column('to_user', sa.Integer(), nullable=False),
    sa.Column('from_assignment', sa.Integer(), nullable=False),
    sa.Column('to_assignment', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'accepted', 'rejected', 'expired', 'pending_admin', 'applied', name='swap_status', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['from_assignment'], ['assignments.id'], name=op.f('fk_swap_requests_from_assignment_assignments'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['from_user'], ['users.id'], name=op.f('fk_swap_requests_from_user_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_assignment'], ['assignments.id'], name=op.f('fk_swap_requests_to_assignment_assignments'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_user'], ['users.id'], name=op.f('fk_swap_requests_to_user_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['week_id'], ['weeks.id'], name=op.f('fk_swap_requests_week_id_weeks'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_swap_requests'))
    )
    with op.batch_alter_table('swap_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_swap_requests_from_user'), ['from_user'], unique=False)
        batch_op.create_index(batch_op.f('ix_swap_requests_to_user'), ['to_user'], unique=False)
        batch_op.create_index(batch_op.f('ix_swap_requests_week_id'), ['week_id'], unique=False)



def downgrade() -> None:
    """Drop the §6 schema (children before parents, for the FKs)."""
    with op.batch_alter_table('swap_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_swap_requests_week_id'))
        batch_op.drop_index(batch_op.f('ix_swap_requests_to_user'))
        batch_op.drop_index(batch_op.f('ix_swap_requests_from_user'))

    op.drop_table('swap_requests')
    op.drop_table('solver_state')
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_sessions_expires_at'))

    op.drop_table('sessions')
    with op.batch_alter_table('sacrifice_proposals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sacrifice_proposals_week_id'))
        batch_op.drop_index(batch_op.f('ix_sacrifice_proposals_user_id'))

    op.drop_table('sacrifice_proposals')
    with op.batch_alter_table('notifications', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notifications_user_id'))

    op.drop_table('notifications')
    with op.batch_alter_table('constraints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_constraints_week_id'))
        batch_op.drop_index(batch_op.f('ix_constraints_user_id'))

    op.drop_table('constraints')
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_log_actor_id'))

    op.drop_table('audit_log')
    with op.batch_alter_table('assignments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_assignments_week_id'))
        batch_op.drop_index(batch_op.f('ix_assignments_user_id'))

    op.drop_table('assignments')
    op.drop_table('weeks')
    op.drop_table('users')
