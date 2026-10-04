"""Voice sessions, their event stream, raw provider webhooks and coding artefacts."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sg_core.models.base import Base, created_at, str_enum, updated_at, uuid_pk
from sg_core.models.enums import (
    Character,
    EventSource,
    ProviderEventStatus,
    SandboxRunStatus,
    SessionStatus,
)


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    character: Mapped[Character] = mapped_column(str_enum(Character, "character"))
    # concept_exam, teach_back, technical_interview, hr_interview, panel_interview,
    # accountability_call, morning_talk, weekly_recap, ... (free-form so new modes need no DDL)
    mode: Mapped[str] = mapped_column(String(64))
    status: Mapped[SessionStatus] = mapped_column(
        str_enum(SessionStatus, "status"), server_default=SessionStatus.CREATED.value
    )
    agent_id: Mapped[str | None] = mapped_column(String(128))
    agent_version: Mapped[str | None] = mapped_column(String(128))
    el_conversation_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    # Source versions this session (and its judge) used, retained for replay.
    curriculum_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("curricula.id", ondelete="SET NULL")
    )
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL")
    )
    is_test: Mapped[bool] = mapped_column(server_default=text("false"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column()
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class SessionEvent(Base):
    """TimescaleDB hypertable partitioned on `occurred_at` (see the baseline migration).

    The primary key includes the time column, as hypertables require. Nothing may hold a
    foreign key to this table.
    """

    __tablename__ = "session_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", "occurred_at"),
        Index("ix_session_events_occurred_at", text("occurred_at DESC")),
        Index("ix_session_events_session_occurred", "session_id", text("occurred_at DESC")),
        Index("ix_session_events_user_occurred", "user_id", text("occurred_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(server_default=text("gen_random_uuid()"))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(64))
    source: Mapped[EventSource] = mapped_column(str_enum(EventSource, "source"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class ProviderEvent(Base):
    """Raw verified webhook, stored before any processing. Unique per provider event id."""

    __tablename__ = "provider_events"
    __table_args__ = (
        Index("uq_provider_events_provider_event", "provider", "event_id", unique=True),
        Index("ix_provider_events_status_received", "status", "received_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(32))  # elevenlabs, twilio, clerk, e2b, ...
    event_id: Mapped[str] = mapped_column(String(256))
    event_type: Mapped[str] = mapped_column(String(128))
    signature_verified: Mapped[bool] = mapped_column()
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[ProviderEventStatus] = mapped_column(
        str_enum(ProviderEventStatus, "status"),
        server_default=ProviderEventStatus.RECEIVED.value,
    )
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = created_at()
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CodeSnapshot(Base):
    __tablename__ = "code_snapshots"
    __table_args__ = (Index("ix_code_snapshots_session_captured", "session_id", "captured_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    problem_ref: Mapped[str | None] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    trigger: Mapped[str] = mapped_column(String(32))  # autosave | run | submit
    captured_at: Mapped[datetime] = created_at()


class SandboxRun(Base):
    __tablename__ = "sandbox_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    code_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_snapshots.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider_run_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[SandboxRunStatus] = mapped_column(
        str_enum(SandboxRunStatus, "status"), server_default=SandboxRunStatus.QUEUED.value
    )
    tests_passed: Mapped[int | None] = mapped_column()
    tests_total: Mapped[int | None] = mapped_column()
    duration_ms: Mapped[int | None] = mapped_column()
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HintGiven(Base):
    """Every hint is recorded so later evidence is marked assisted."""

    __tablename__ = "hints_given"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="SET NULL")
    )
    question_ref: Mapped[str | None] = mapped_column(String(128))
    level: Mapped[int] = mapped_column(SmallInteger)  # 1 = nudge ... higher = more revealing
    content: Mapped[str] = mapped_column(Text)
    given_at: Mapped[datetime] = created_at()
