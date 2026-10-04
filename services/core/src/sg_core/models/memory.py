"""Memory Persistence Engine storage (C09). Writes are append-only: corrections insert a
new row and point the old one at it through `superseded_by_id`."""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, DateTime, Float, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sg_core.models.base import EMBEDDING_DIM, Base, created_at, str_enum, uuid_pk
from sg_core.models.enums import Character, MemoryLayer, MemorySource, MemoryStatus


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_user_layer_status", "user_id", "layer", "status"),
        Index(
            "ix_memories_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    layer: Mapped[MemoryLayer] = mapped_column(str_enum(MemoryLayer, "layer"))
    kind: Mapped[str] = mapped_column(String(64))  # goal, misconception, preference, ...
    content: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    source: Mapped[MemorySource] = mapped_column(str_enum(MemorySource, "source"))
    source_character: Mapped[Character | None] = mapped_column(
        str_enum(Character, "source_character")
    )
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    evidence_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]")
    )
    status: Mapped[MemoryStatus] = mapped_column(
        str_enum(MemoryStatus, "status"), server_default=MemoryStatus.PROVISIONAL.value
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    # Private reflections: characters allowed to read this memory. Null means all.
    visible_to: Mapped[list[str] | None] = mapped_column(ARRAY(String(40)))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL")
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = created_at()
