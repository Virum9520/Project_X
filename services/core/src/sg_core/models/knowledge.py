"""Uploaded documents, their versions, embedded chunks and concept mappings (C08).

Uploaded text is reference data, never instructions, and never awards mastery.
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sg_core.models.base import EMBEDDING_DIM, Base, created_at, str_enum, uuid_pk
from sg_core.models.enums import DocumentKind, DocumentVersionStatus, ReviewStatus


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[DocumentKind] = mapped_column(str_enum(DocumentKind, "kind"))
    title: Mapped[str] = mapped_column(String(300))
    # The version authorized sessions read. Previous version stays active until indexing succeeds.
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL", use_alter=True)
    )
    created_at: Mapped[datetime] = created_at()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        Index("uq_document_versions_document_version", "document_id", "version", unique=True),
        Index("uq_document_versions_document_hash", "document_id", "content_hash", unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column()
    content_hash: Mapped[str] = mapped_column(String(64))  # sha256 hex
    storage_key: Mapped[str] = mapped_column(String(512))  # ObjectStore key of the original
    original_filename: Mapped[str | None] = mapped_column(String(300))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    page_count: Mapped[int | None] = mapped_column()
    status: Mapped[DocumentVersionStatus] = mapped_column(
        str_enum(DocumentVersionStatus, "status"),
        server_default=DocumentVersionStatus.UPLOADED.value,
    )
    extraction_flags: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Chunk(Base):
    """A searchable slice of a document version. `user_id` is denormalized for isolation."""

    __tablename__ = "chunks"
    __table_args__ = (
        Index("uq_chunks_version_ordinal", "document_version_id", "ordinal", unique=True),
        Index(
            "ix_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column()
    content: Mapped[str] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column()
    page_end: Mapped[int | None] = mapped_column()
    token_count: Mapped[int | None] = mapped_column()
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = created_at()


class ConceptMapping(Base):
    """An AI-proposed link from document material to a catalogue concept."""

    __tablename__ = "concept_mappings"
    __table_args__ = (Index("ix_concept_mappings_version", "document_version_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"))
    concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), index=True
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[ReviewStatus] = mapped_column(
        str_enum(ReviewStatus, "status"), server_default=ReviewStatus.PROPOSED.value
    )
    method: Mapped[str] = mapped_column(String(32))  # llm | manual | rule
    created_at: Mapped[datetime] = created_at()
