"""SQLAlchemy models — a direct transcription of spec §6.

The table and column names here are the spec's, verbatim (including
`swap_requests.from_user` and friends, which are FK columns despite the name).
Foreign keys, indexes and the timestamp defaults are the only things §6 leaves
to the implementation.

All datetime columns are `UtcDateTime`: UTC in the DB, tz-aware in Python,
converted to Europe/Rome only at the edges.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UtcDateTime, enum_column, utcnow
from app.enums import (
    AssignmentRole,
    AssignmentSlot,
    AssignmentSource,
    ConstraintKind,
    ConstraintSlot,
    Day,
    Language,
    SacrificeStatus,
    SwapStatus,
    UserRole,
    WeekStatus,
)
from app.security import new_ics_token


class User(Base):
    """§6 users. Root (§5) is a normal row with `is_root=true`, hidden from
    listings, worker pickers and role-based notification fan-out."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[UserRole] = mapped_column(enum_column(UserRole, "user_role"), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_root: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Nullable: §6 does not require an address, and the email channel is opt-out
    # per user (§10) — a user with notifications off needs no address.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_notifications: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    language: Mapped[Language] = mapped_column(
        enum_column(Language, "language"), nullable=False, default=Language.IT
    )
    # §7 /export/ics bearer credential (v1.7): per-user, random, opaque — the
    # calendar-feed URL is the leakiest credential in the system (pasted into
    # calendar apps, synced to family devices), so revocation must be per-user
    # regeneration, never a SECRET_KEY rotation. Unique: the feed URL must
    # resolve to exactly one user. NEVER serialized by any response model except
    # to its own user.
    ics_token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, default=new_ics_token
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    solver_state: Mapped[SolverState | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class Session(Base):
    """§6 sessions — the server-side store behind §7's signed cookie.

    `id` is the opaque session token itself (string, not an autoincrement int):
    it is the value carried by the cookie and looked up on every request.
    """

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, index=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class Week(Base):
    """§6 weeks. Identified by its Monday; the §3 window closes Sun 17:00
    Europe/Rome before `monday_date`."""

    __tablename__ = "weeks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monday_date: Mapped[dt.date] = mapped_column(Date, unique=True, nullable=False)
    status: Mapped[WeekStatus] = mapped_column(
        enum_column(WeekStatus, "week_status"), nullable=False, default=WeekStatus.OPEN
    )
    solved_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    locked_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)

    constraints: Mapped[list[Constraint]] = relationship(
        back_populates="week", cascade="all, delete-orphan"
    )
    assignments: Mapped[list[Assignment]] = relationship(
        back_populates="week", cascade="all, delete-orphan"
    )


class Constraint(Base):
    """§6 constraints. Editable while `week.status = open`; submission is an
    upsert on (user, week, day, slot) — the unique constraint is what makes that
    upsert well-defined (§3)."""

    __tablename__ = "constraints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week_id: Mapped[int] = mapped_column(
        ForeignKey("weeks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day: Mapped[Day] = mapped_column(enum_column(Day, "day"), nullable=False)
    # §6: ENUM(am, pm, full_day) — wider than an assignment's slot. §3 makes
    # full_day and am/pm mutually exclusive within a day, at the app layer.
    slot: Mapped[ConstraintSlot] = mapped_column(
        enum_column(ConstraintSlot, "constraint_slot"), nullable=False
    )
    kind: Mapped[ConstraintKind] = mapped_column(
        enum_column(ConstraintKind, "constraint_kind"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        # §6: one constraint per (user, week, day, slot) — the upsert key.
        UniqueConstraint("user_id", "week_id", "day", "slot"),
    )

    user: Mapped[User] = relationship()
    week: Mapped[Week] = relationship(back_populates="constraints")


class Assignment(Base):
    """§6 assignments. One row per worked slot, weekdays from the solver and
    weekends from the fixed template (H5)."""

    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_id: Mapped[int] = mapped_column(
        ForeignKey("weeks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day: Mapped[Day] = mapped_column(enum_column(Day, "day"), nullable=False)
    # §6: ENUM(am, pm) only — an assignment is always a concrete slot, so a
    # 'full_day' weekend template row is emitted as two rows (am + pm).
    slot: Mapped[AssignmentSlot] = mapped_column(
        enum_column(AssignmentSlot, "assignment_slot"), nullable=False
    )
    role: Mapped[AssignmentRole] = mapped_column(
        enum_column(AssignmentRole, "assignment_role"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[AssignmentSource] = mapped_column(
        enum_column(AssignmentSource, "assignment_source"), nullable=False
    )

    __table_args__ = (
        # §6: exactly one holder per (week, day, slot, role) — H1's coverage
        # uniqueness enforced by the database, not just the solver. Scoped to
        # Mon–Fri: the H5 weekend template deliberately has TWO spiaggini per slot
        # (Pasha and Amir full-day), which a table-wide key would reject, so
        # weekend rows are exempt and their integrity comes from
        # `emit_weekend_template` being their sole writer.
        Index(
            "uq_assignments_weekday_slot",
            "week_id",
            "day",
            "slot",
            "role",
            unique=True,
            sqlite_where=text("day IN ('mon', 'tue', 'wed', 'thu', 'fri')"),
        ),
    )

    week: Mapped[Week] = relationship(back_populates="assignments")
    user: Mapped[User] = relationship()


class SwapRequest(Base):
    """§6 swap_requests — the §4 state machine's persistence."""

    __tablename__ = "swap_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_id: Mapped[int] = mapped_column(
        ForeignKey("weeks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_user: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_user: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_assignment: Mapped[int] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    to_assignment: Mapped[int] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[SwapStatus] = mapped_column(
        enum_column(SwapStatus, "swap_status"), nullable=False, default=SwapStatus.PENDING
    )
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)
    # Set when the request leaves `pending`; the 48 h expiry (§4) is measured
    # from `created_at`.
    resolved_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)

    week: Mapped[Week] = relationship()
    requester: Mapped[User] = relationship(foreign_keys=[from_user])
    target: Mapped[User] = relationship(foreign_keys=[to_user])
    requester_assignment: Mapped[Assignment] = relationship(foreign_keys=[from_assignment])
    target_assignment: Mapped[Assignment] = relationship(foreign_keys=[to_assignment])


class SacrificeProposal(Base):
    """§6 sacrifice_proposals — §2.3's "move your free day to {day}?" offer.

    Never auto-resolves: it sits `pending` until the named worker accepts or
    declines.
    """

    __tablename__ = "sacrifice_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_id: Mapped[int] = mapped_column(
        ForeignKey("weeks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # A free day (H3: Mon–Thu); the Mon–Thu narrowing is a solver/app rule, the
    # column's domain is the full §6 day enum.
    proposed_free_day: Mapped[Day] = mapped_column(enum_column(Day, "day"), nullable=False)
    status: Mapped[SacrificeStatus] = mapped_column(
        enum_column(SacrificeStatus, "sacrifice_status"),
        nullable=False,
        default=SacrificeStatus.PENDING,
    )
    # §8 minimal unsat core as DATA — a list of {worker_id, day, slot} dicts for
    # the blocking hard requests. Rendered in the viewer's language by the §9
    # dictionaries; never a pre-formatted sentence (v1.5).
    conflict: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    __table_args__ = (
        # §6 (v1.6): one proposal per (week, worker). Safe by construction —
        # Friday is the only reachable sacrifice day (§2.3 corollary), so one
        # worker can never legitimately hold two proposals in a week — and
        # load-bearing: the ACCEPTED row is the grant of record (§2.1 H3), so a
        # second row for the same worker could silently widen the H3 domain twice.
        UniqueConstraint("week_id", "user_id"),
    )

    week: Mapped[Week] = relationship()
    user: Mapped[User] = relationship()


class Notification(Base):
    """§6 notifications — the in-app channel's rows, written by `notify()` (§10).

    `event_type` is a free string, not an enum: §6 declares no enum for it and
    §10 expects new events (PWA push era) without a migration.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    user: Mapped[User] = relationship()


class AuditLog(Base):
    """§6 audit_log — every lock, swap, override and sacrifice transition."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Nullable: scheduled jobs (§11 cron solve, swap expiry) act with no human
    # actor, and those transitions still have to be logged.
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    actor: Mapped[User | None] = relationship()


class SolverState(Base):
    """§6 solver_state — keyed by user_id, no surrogate id.

    Carries each worker's last worked slot across the week boundary so S2's
    alternation penalty can see the previous week (§2.2).
    """

    __tablename__ = "solver_state"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    last_worked_slot: Mapped[AssignmentSlot | None] = mapped_column(
        enum_column(AssignmentSlot, "assignment_slot"), nullable=True
    )
    last_worked_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    user: Mapped[User] = relationship(back_populates="solver_state")
