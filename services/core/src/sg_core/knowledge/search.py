"""Vector search over one learner's own documents.

Isolation is enforced in SQL, not by the caller: every query filters `chunks.user_id` and joins
through `documents.user_id`, deleted documents are excluded, and only chunks from an *active*
version are searchable (or from the version a session is pinned to). Chunks embedded by a
different model than the query are never compared.

Results are data. Passages are flattened of control characters, bounded in length and returned
with their document title and page reference; callers must present them as quoted material, never
as instructions.
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.memory.embeddings import EmbeddingProvider
from sg_core.models.curriculum import Concept
from sg_core.models.enums import DocumentKind, ReviewStatus
from sg_core.models.knowledge import Chunk, ConceptMapping, Document, DocumentVersion

MAX_QUERY_CHARS = 500
MAX_PASSAGE_CHARS = 800
DEFAULT_LIMIT = 4
MAX_LIMIT = 8
MIN_SCORE = 0.2  # cosine similarity floor: below this a passage is noise
SEARCHABLE_KINDS = (DocumentKind.STUDY_MATERIAL, DocumentKind.OTHER)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class Passage:
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_id: uuid.UUID
    title: str
    page_start: int | None
    page_end: int | None
    text: str
    score: float

    @property
    def reference(self) -> str:
        if self.page_start is None:
            return self.title
        if self.page_end in (None, self.page_start):
            return f"{self.title}, p. {self.page_start}"
        return f"{self.title}, pp. {self.page_start}-{self.page_end}"


def flatten(text: str, limit: int) -> str:
    flat = _CONTROL.sub(" ", text).strip()
    flat = re.sub(r"[ \t]+", " ", flat)
    flat = re.sub(r"\n{3,}", "\n\n", flat)
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


async def searchable_version_ids(
    session: AsyncSession, user_id: uuid.UUID, pinned_version_id: uuid.UUID | None = None
) -> list[uuid.UUID]:
    """Active version of each of the learner's live documents.

    A session pinned to a version keeps reading it: it replaces the active version of its own
    document (even if a newer one went live mid-session), provided the learner owns it.
    """
    rows = (
        await session.execute(
            select(Document.id, Document.active_version_id).where(
                Document.user_id == user_id,
                Document.deleted_at.is_(None),
                Document.kind.in_(SEARCHABLE_KINDS),
                Document.active_version_id.is_not(None),
            )
        )
    ).all()
    active: dict[uuid.UUID, uuid.UUID] = {
        doc_id: version_id for doc_id, version_id in rows if version_id is not None
    }
    if pinned_version_id is not None:
        pinned_document = await session.scalar(
            select(Document.id)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .where(
                DocumentVersion.id == pinned_version_id,
                Document.user_id == user_id,
                Document.deleted_at.is_(None),
                Document.kind.in_(SEARCHABLE_KINDS),
            )
        )
        if pinned_document is not None:
            active[pinned_document] = pinned_version_id
    return list(active.values())


async def _concept_ids(session: AsyncSession, concept: str) -> list[uuid.UUID]:
    """Resolve a concept reference: a stable key like `dsa.graphs` (any curriculum version)
    or a concept UUID."""
    try:
        return [uuid.UUID(concept)]
    except ValueError:
        pass
    return list(await session.scalars(select(Concept.id).where(Concept.key == concept)))


async def search_documents(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    query: str,
    embedder: EmbeddingProvider,
    concept: str | None = None,
    pinned_version_id: uuid.UUID | None = None,
    limit: int = DEFAULT_LIMIT,
    min_score: float = MIN_SCORE,
) -> list[Passage]:
    text = " ".join(_CONTROL.sub(" ", query).split())[:MAX_QUERY_CHARS]
    if not text:
        return []
    limit = max(1, min(limit, MAX_LIMIT))
    version_ids = await searchable_version_ids(session, user_id, pinned_version_id)
    if not version_ids:
        return []
    concept_ids: Sequence[uuid.UUID] | None = None
    if concept:
        concept_ids = await _concept_ids(session, concept)
        if not concept_ids:
            return []

    [vector] = await embedder.embed([text])
    distance = Chunk.embedding.cosine_distance(vector)
    statement = (
        select(Chunk, Document.id, Document.title, distance)
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            Chunk.user_id == user_id,
            Document.user_id == user_id,
            Document.deleted_at.is_(None),
            Chunk.document_version_id.in_(version_ids),
            Chunk.embedding.is_not(None),
            Chunk.embedding_model == embedder.model,
        )
        .order_by(distance)
        .limit(limit)
    )
    if concept_ids is not None:
        statement = statement.where(
            Chunk.id.in_(
                select(ConceptMapping.chunk_id).where(
                    ConceptMapping.concept_id.in_(concept_ids),
                    ConceptMapping.status != ReviewStatus.REJECTED,
                    ConceptMapping.chunk_id.is_not(None),
                )
            )
        )
    rows = (await session.execute(statement)).all()
    passages: list[Passage] = []
    for chunk, document_id, title, dist in rows:
        score = 1.0 - float(dist)
        if score < min_score:
            continue
        passages.append(
            Passage(
                document_id=document_id,
                document_version_id=chunk.document_version_id,
                chunk_id=chunk.id,
                title=flatten(title, 120),
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                text=flatten(chunk.content, MAX_PASSAGE_CHARS),
                score=round(score, 4),
            )
        )
    return passages
