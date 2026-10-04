"""Versioned curriculum: concepts, prerequisite edges and rubrics (content owned by C07)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sg_core.models.base import Base, created_at, str_enum, uuid_pk
from sg_core.models.enums import ConceptEdgeKind, CurriculumStatus, Dimension


class Curriculum(Base):
    """One loaded curriculum version, e.g. `cs-core` / `v1`."""

    __tablename__ = "curricula"
    __table_args__ = (
        Index("uq_curricula_key_version", "key", "version", unique=True),
        Index(
            "uq_curricula_active_key",
            "key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[CurriculumStatus] = mapped_column(
        str_enum(CurriculumStatus, "status"), server_default=CurriculumStatus.DRAFT.value
    )
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()


class Concept(Base):
    """A plant in the garden. `key` is stable across curriculum versions."""

    __tablename__ = "concepts"
    __table_args__ = (
        Index("uq_concepts_curriculum_key", "curriculum_id", "key", unique=True),
        Index("ix_concepts_curriculum_domain", "curriculum_id", "domain"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    curriculum_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("curricula.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(128))
    # Grove: dsa, os, networks, databases, system_design, behavioral, ...
    domain: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[int | None] = mapped_column(SmallInteger)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = created_at()


class ConceptEdge(Base):
    """`from_concept` is a prerequisite of (or related to) `to_concept`."""

    __tablename__ = "concept_edges"
    __table_args__ = (
        CheckConstraint("from_concept_id <> to_concept_id", name="no_self_edge"),
        Index("ix_concept_edges_to", "to_concept_id"),
    )

    from_concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True
    )
    to_concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[ConceptEdgeKind] = mapped_column(
        str_enum(ConceptEdgeKind, "kind"),
        primary_key=True,
        server_default=ConceptEdgeKind.PREREQUISITE.value,
    )


class Rubric(Base):
    """A versioned scoring rubric. `concept_id` is null for communication rubrics."""

    __tablename__ = "rubrics"
    __table_args__ = (Index("uq_rubrics_key_version", "key", "version", unique=True),)

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column()
    curriculum_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("curricula.id", ondelete="CASCADE")
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), index=True
    )
    dimension: Mapped[Dimension | None] = mapped_column(str_enum(Dimension, "dimension"))
    criteria: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()
