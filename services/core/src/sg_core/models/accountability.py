"""Commitments and scheduled accountability calls (C18), plus voice-clone consent (C19)."""

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from sg_core.models.base import Base, created_at, str_enum, updated_at, uuid_pk
from sg_core.models.enums import CallChannelKind, CallState, CommitmentStatus, CompletionSource


class Commitment(Base):
    __tablename__ = "commitments"
    __table_args__ = (Index("ix_commitments_user_status_due", "user_id", "status", "due_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[CommitmentStatus] = mapped_column(
        str_enum(CommitmentStatus, "status"), server_default=CommitmentStatus.OPEN.value
    )
    completion_source: Mapped[CompletionSource | None] = mapped_column(
        str_enum(CompletionSource, "completion_source")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # What the learner last said about it (done, partly_done, not_done, wants_to_change). Kept
    # apart from `status`/`completion_source`: a report never becomes observed evidence.
    reported_status: Mapped[str | None] = mapped_column(String(20))
    reported_note: Mapped[str | None] = mapped_column(String(400))
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    concept_key: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CallSchedule(Base):
    __tablename__ = "call_schedules"
    __table_args__ = (
        CheckConstraint("days <@ ARRAY[1,2,3,4,5,6,7]::smallint[]", name="iso_weekdays"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[CallChannelKind] = mapped_column(str_enum(CallChannelKind, "channel"))
    destination: Mapped[str | None] = mapped_column(String(32))  # E.164, phone channel only
    destination_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tz: Mapped[str] = mapped_column(String(64))  # IANA
    local_time: Mapped[time] = mapped_column(Time)
    days: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))  # ISO weekday 1=Mon..7=Sun
    tone: Mapped[str | None] = mapped_column(String(32))
    max_duration_seconds: Mapped[int] = mapped_column(server_default=text("120"))
    consent_ver: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CallOccurrence(Base):
    """One intended call. Unique per schedule and local date so restarts or edits never
    create a duplicate. Call-now test calls have no schedule and dedupe on `request_id`."""

    __tablename__ = "call_occurrences"
    __table_args__ = (
        Index("uq_call_occurrences_schedule_local_date", "schedule_id", "local_date", unique=True),
        Index("ix_call_occurrences_state_due", "state", "scheduled_for"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_schedules.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    local_date: Mapped[date] = mapped_column(Date)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # UTC instant
    state: Mapped[CallState] = mapped_column(
        str_enum(CallState, "state"), server_default=CallState.SCHEDULED.value
    )
    is_test: Mapped[bool] = mapped_column(server_default=text("false"))
    request_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class CallAttempt(Base):
    """A dispatch of an occurrence. Intentional retries are separate, linked attempts."""

    __tablename__ = "call_attempts"
    __table_args__ = (
        Index("uq_call_attempts_occurrence_no", "occurrence_id", "attempt_no", unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    occurrence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("call_occurrences.id", ondelete="CASCADE")
    )
    attempt_no: Mapped[int] = mapped_column(SmallInteger)
    previous_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_attempts.id", ondelete="SET NULL")
    )
    channel: Mapped[CallChannelKind] = mapped_column(str_enum(CallChannelKind, "channel"))
    state: Mapped[CallState] = mapped_column(
        str_enum(CallState, "state"), server_default=CallState.QUEUED.value
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    el_conversation_id: Mapped[str | None] = mapped_column(String(128))
    twilio_call_sid: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class PushSubscription(Base):
    """A browser Web Push subscription that `WebCallChannel` rings. Revocation keeps the row."""

    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(256))
    auth: Mapped[str] = mapped_column(String(128))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = created_at()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VoiceConsent(Base):
    """Consent recording for Future-Self voice cloning. Revocation keeps the row."""

    __tablename__ = "voice_consents"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    consent_ver: Mapped[str] = mapped_column(String(32))
    recording_s3: Mapped[str] = mapped_column(String(512))  # ObjectStore key
    phrase_verified: Mapped[bool] = mapped_column(server_default=text("false"))
    verified_transcript: Mapped[str | None] = mapped_column(Text)
    voice_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = created_at()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
