"""Evidence, judge assessments, disputes and the garden projection (C10, C11).

Garden rows change only through the deterministic, versioned rules engine, and every
change cites the assessments (and through them, the evidence) that caused it.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sg_core.models.base import Base, created_at, str_enum, updated_at, uuid_pk
from sg_core.models.enums import (
    AssessmentOutcome,
    AssessmentStatus,
    Assistance,
    Dimension,
    DisputeStatus,
    PlantStatus,
)


class EvidenceItem(Base):
    """One attributable observation: a quote, an answer, a code run."""

    __tablename__ = "evidence_items"
    __table_args__ = (
        Index("ix_evidence_items_user_concept", "user_id", "concept_id", "occurred_at"),
        Index("ix_evidence_items_session", "session_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id", ondelete="RESTRICT"))
    dimension: Mapped[Dimension] = mapped_column(str_enum(Dimension, "dimension"))
    assistance: Mapped[Assistance] = mapped_column(str_enum(Assistance, "assistance"))
    kind: Mapped[str] = mapped_column(String(32))  # quote | answer | code_run | teach_back
    quote: Mapped[str | None] = mapped_column(Text)
    transcript_start_s: Mapped[float | None] = mapped_column(Numeric(10, 3))
    transcript_end_s: Mapped[float | None] = mapped_column(Numeric(10, 3))
    code_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("code_snapshots.id", ondelete="SET NULL")
    )
    sandbox_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sandbox_runs.id", ondelete="SET NULL")
    )
    hint_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]")
    )
    # Problem family, so repeats of the same answer are not counted as independent.
    problem_family: Mapped[str | None] = mapped_column(String(128))
    # Deterministic key so a replayed webhook cannot create the same evidence twice.
    dedupe_key: Mapped[str] = mapped_column(String(256), unique=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class Assessment(Base):
    """A judge's verdict on one concept and dimension. Re-judging adds a new `rev`."""

    __tablename__ = "assessments"
    __table_args__ = (
        Index(
            "uq_assessments_session_concept_dim_rev",
            "session_id",
            "concept_id",
            "dimension",
            "rev",
            unique=True,
        ),
        Index("ix_assessments_user_concept", "user_id", "concept_id"),
        CheckConstraint("uncertainty IS NULL OR uncertainty BETWEEN 0 AND 1", name="uncertainty"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id", ondelete="RESTRICT"))
    dimension: Mapped[Dimension] = mapped_column(str_enum(Dimension, "dimension"))
    rev: Mapped[int] = mapped_column(server_default=text("1"))
    outcome: Mapped[AssessmentOutcome] = mapped_column(str_enum(AssessmentOutcome, "outcome"))
    assistance: Mapped[Assistance] = mapped_column(str_enum(Assistance, "assistance"))
    score: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    judge_model: Mapped[str] = mapped_column(String(128))
    rubric_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("rubrics.id", ondelete="RESTRICT")
    )
    rubric_ver: Mapped[int | None] = mapped_column()
    status: Mapped[AssessmentStatus] = mapped_column(
        str_enum(AssessmentStatus, "status"), server_default=AssessmentStatus.PENDING.value
    )
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assessments.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = created_at()


class AssessmentDispute(Base):
    __tablename__ = "assessment_disputes"

    id: Mapped[uuid.UUID] = uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), index=True
    )
    raised_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[DisputeStatus] = mapped_column(
        str_enum(DisputeStatus, "status"), server_default=DisputeStatus.OPEN.value
    )
    resolution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GardenRevision(Base):
    """Append-only, per-learner revision of the garden. `rev` gives optimistic concurrency
    and lets the dashboard time-travel; `changes` holds per-concept before/after states."""

    __tablename__ = "garden_revisions"
    __table_args__ = (Index("uq_garden_revisions_user_rev", "user_id", "rev", unique=True),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rev: Mapped[int] = mapped_column()
    rule_ver: Mapped[str] = mapped_column(String(64))
    assessment_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]")
    )
    reason: Mapped[str] = mapped_column(String(64))  # onboarding | assessment | decay | correction
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = created_at()


class PlantState(Base):
    """Current projection of one concept plant for one learner."""

    __tablename__ = "plant_states"
    __table_args__ = (
        Index("ix_plant_states_user_status", "user_id", "status"),
        Index("ix_plant_states_user_review", "user_id", "next_review_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[PlantStatus] = mapped_column(
        str_enum(PlantStatus, "status"), server_default=PlantStatus.UNASSESSED.value
    )
    # {"explanation": {"independent": 0.6, "assisted": 0.8}, ...}
    dimension_scores: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    garden_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("garden_revisions.id", ondelete="SET NULL")
    )
    last_evidence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = updated_at()
