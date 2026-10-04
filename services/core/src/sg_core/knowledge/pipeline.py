"""The ingestion pipeline for one document version: extract, chunk, map, embed, activate.

    uploaded -> extracting -> mapping -> embedding -> active
                       \\________ any step fails ______/--> failed

Guarantees:

- **Activation is last and atomic.** Chunks and concept mappings are written in the same
  transaction that flips `documents.active_version_id`. Until then sessions keep reading the
  previously active version; a failure leaves it untouched and only marks the new version
  `failed`. Superseded versions keep their chunks so sessions pinned to them (and the judge that
  cited them) still resolve.
- **Out-of-order safety.** If a newer version already went active, a late-finishing older one is
  marked `superseded` instead of replacing it.
- **Idempotent and retryable.** Re-running a version replaces its own chunks and mappings;
  `active`/`superseded` versions are a no-op. Transient provider errors are re-raised so the job
  runner retries; permanent problems (corrupt file, nothing to read) fail the version once.
- **Documents are data.** Text is extracted, chunked and embedded; it is quoted inside delimited
  blocks for the mapper (which has no tools and whose output is validated against the catalogue).
  Nothing in a document is executed, followed or turned into mastery.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sg_core.economics.usage import UsageContext
from sg_core.knowledge.chunking import chunk_pages
from sg_core.knowledge.errors import ExtractionError, KnowledgeError
from sg_core.knowledge.extract import OcrProvider, extract_document
from sg_core.knowledge.mapping import (
    CatalogConcept,
    ConceptMapper,
    KeywordConceptMapper,
    MappingProposal,
)
from sg_core.knowledge.providers import embedder_scope, mapper_scope
from sg_core.logging import get_logger
from sg_core.memory.embeddings import EmbeddingProvider
from sg_core.models.curriculum import Concept, Curriculum
from sg_core.models.enums import (
    CostCenter,
    CurriculumStatus,
    DocumentKind,
    DocumentVersionStatus,
    ReviewStatus,
)
from sg_core.models.knowledge import Chunk, ConceptMapping, Document, DocumentVersion
from sg_core.providers.base import ProviderError, ProviderNotConfiguredError
from sg_core.providers.storage import ObjectNotFoundError, ObjectStore

log = get_logger(__name__)

COMPONENT = "knowledge.ingest"
EMBED_BATCH = 64
NOOP_STATUSES = frozenset({DocumentVersionStatus.ACTIVE, DocumentVersionStatus.SUPERSEDED})
MAX_ERROR_CHARS = 500


@dataclass(frozen=True, slots=True)
class IngestResult:
    version_id: uuid.UUID
    status: DocumentVersionStatus
    chunks: int = 0
    mappings: int = 0
    detail: str | None = None


def usage_context(user_id: uuid.UUID, version_id: uuid.UUID, step: str) -> UsageContext:
    return UsageContext(
        cost_center=CostCenter.LEARNER,
        component=f"{COMPONENT}.{step}",
        user_id=user_id,
        idempotency_key=f"knowledge:{version_id}:{step}",
    )


async def load_catalog(session: AsyncSession) -> tuple[list[CatalogConcept], dict[str, uuid.UUID]]:
    """Concepts of the active curriculum, plus key -> id. Empty if none is active."""
    rows = (
        await session.execute(
            select(Concept)
            .join(Curriculum, Curriculum.id == Concept.curriculum_id)
            .where(Curriculum.status == CurriculumStatus.ACTIVE)
            .order_by(Concept.key)
        )
    ).scalars()
    catalog: list[CatalogConcept] = []
    ids: dict[str, uuid.UUID] = {}
    for concept in rows:
        attrs = concept.attributes or {}
        catalog.append(
            CatalogConcept(
                key=concept.key,
                title=concept.title,
                domain=concept.domain,
                aliases=tuple(str(a) for a in attrs.get("aliases") or ()),
                topic=attrs.get("topic"),
            )
        )
        ids[concept.key] = concept.id
    return catalog, ids


async def _set_status(
    session: AsyncSession, version: DocumentVersion, status: DocumentVersionStatus
) -> None:
    version.status = status
    await session.commit()  # progress is visible to the learner between steps


async def run_ingestion(
    session: AsyncSession,
    version_id: uuid.UUID,
    *,
    store: ObjectStore,
    embedder: EmbeddingProvider,
    mapper: ConceptMapper | None = None,
    ocr: OcrProvider | None = None,
) -> IngestResult:
    """Run (or resume) ingestion for one version. Commits as it goes."""
    version = await session.scalar(
        select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise KnowledgeError(f"unknown document version {version_id}")
    if version.status in NOOP_STATUSES:
        return IngestResult(version.id, version.status, detail="already processed")
    document = await session.get(Document, version.document_id)
    if document is None or document.deleted_at is not None:
        version.status = DocumentVersionStatus.FAILED
        version.error = "document was deleted"
        await session.commit()
        return IngestResult(version.id, version.status, detail=version.error)
    user_id = document.user_id
    document_id = document.id
    version_pk = version.id
    session.sync_session.expire_on_commit = False  # we read ORM rows across commits
    try:
        return await _ingest(
            session, version, document, store=store, embedder=embedder, mapper=mapper, ocr=ocr
        )
    except (KnowledgeError, ProviderError, ProviderNotConfiguredError, ObjectNotFoundError) as exc:
        await session.rollback()
        retryable = isinstance(exc, ProviderError) and exc.retryable
        await _mark_failed(session, version_pk, _describe(exc), flags=getattr(exc, "flags", None))
        log.warning(
            "knowledge.ingest_failed",
            version_id=str(version_pk),
            document_id=str(document_id),
            user_id=str(user_id),
            retryable=retryable,
            error=str(exc)[:200],
        )
        if retryable:
            raise
        return IngestResult(version_pk, DocumentVersionStatus.FAILED, detail=_describe(exc))
    except Exception:
        await session.rollback()
        await _mark_failed(session, version_pk, "unexpected error while processing the document")
        log.exception("knowledge.ingest_crashed", version_id=str(version_pk))
        raise


def _describe(exc: Exception) -> str:
    if isinstance(exc, ProviderNotConfiguredError):
        return "a required provider is not configured"
    if isinstance(exc, ProviderError):
        return f"{exc.provider} was unavailable; this will be retried"[:MAX_ERROR_CHARS]
    if isinstance(exc, ObjectNotFoundError):
        return "the stored file is missing"
    return str(exc)[:MAX_ERROR_CHARS]


async def _mark_failed(
    session: AsyncSession,
    version_id: uuid.UUID,
    message: str,
    *,
    flags: dict[str, Any] | None = None,
) -> None:
    values: dict[str, Any] = {
        "status": DocumentVersionStatus.FAILED,
        "error": message[:MAX_ERROR_CHARS],
    }
    if flags is not None:
        values["extraction_flags"] = flags
    await session.execute(
        update(DocumentVersion)
        .where(
            DocumentVersion.id == version_id,
            DocumentVersion.status.notin_(list(NOOP_STATUSES)),
        )
        .values(**values)
    )
    await session.commit()


async def _ingest(
    session: AsyncSession,
    version: DocumentVersion,
    document: Document,
    *,
    store: ObjectStore,
    embedder: EmbeddingProvider,
    mapper: ConceptMapper | None,
    ocr: OcrProvider | None,
) -> IngestResult:
    user_id = document.user_id
    version.error = None
    await _set_status(session, version, DocumentVersionStatus.EXTRACTING)
    version.page_count = None

    original = await store.get(version.storage_key)
    if hashlib.sha256(original.data).hexdigest() != version.content_hash:
        raise ExtractionError("the stored file does not match its recorded hash")
    mime_type = version.mime_type or original.content_type or ""
    extracted = await extract_document(original.data, mime_type, ocr=ocr)
    flags: dict[str, Any] = dict(extracted.flags)
    version.page_count = extracted.page_count
    chunks = [] if flags.get("empty") else chunk_pages(extracted.pages)
    if not chunks:
        hint = " It looks scanned; upload a text-based PDF." if flags.get("needs_ocr") else ""
        raise ExtractionError(f"no readable text was found in the document.{hint}", flags)

    proposals: list[MappingProposal] = []
    catalog: list[CatalogConcept] = []
    concept_ids: dict[str, uuid.UUID] = {}
    if document.kind is DocumentKind.STUDY_MATERIAL:
        await _set_status(session, version, DocumentVersionStatus.MAPPING)
        catalog, concept_ids = await load_catalog(session)
        if not catalog:
            flags["mapping_skipped"] = "no active curriculum"
        else:
            primary = mapper or KeywordConceptMapper()
            try:
                proposals = await primary.propose(
                    chunks, catalog, usage=usage_context(user_id, version.id, "map")
                )
            except (ProviderError, ProviderNotConfiguredError):
                # Mapping is advisory. Fall back to keywords rather than block the document.
                log.warning("knowledge.map_fallback", version_id=str(version.id), exc_info=True)
                flags["mapping_fallback"] = "keyword"
                proposals = await KeywordConceptMapper().propose(chunks, catalog)

    await _set_status(session, version, DocumentVersionStatus.EMBEDDING)
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = [c.content for c in chunks[start : start + EMBED_BATCH]]
        vectors.extend(await embedder.embed(batch))
    if len(vectors) != len(chunks):
        raise KnowledgeError("embedding count did not match chunk count")

    # Everything below is one transaction: chunks, mappings and activation land together.
    previous_chunk_ids = select(Chunk.id).where(Chunk.document_version_id == version.id)
    await session.execute(
        delete(ConceptMapping).where(ConceptMapping.chunk_id.in_(previous_chunk_ids))
    )
    await session.execute(delete(Chunk).where(Chunk.document_version_id == version.id))
    rows = [
        Chunk(
            document_version_id=version.id,
            user_id=user_id,
            ordinal=c.ordinal,
            content=c.content,
            page_start=c.page_start,
            page_end=c.page_end,
            token_count=c.token_count,
            embedding=vector,
            embedding_model=embedder.model,
        )
        for c, vector in zip(chunks, vectors, strict=True)
    ]
    session.add_all(rows)
    await session.flush()
    chunk_by_ordinal = {row.ordinal: row.id for row in rows}
    for p in proposals:
        session.add(
            ConceptMapping(
                document_version_id=version.id,
                chunk_id=chunk_by_ordinal[p.chunk_ordinal],
                concept_id=concept_ids[p.concept_key],
                confidence=p.confidence,
                status=ReviewStatus.PROPOSED,
                method=p.method,
            )
        )
    version.extraction_flags = flags
    await _activate(session, version, document)
    await session.commit()
    log.info(
        "knowledge.ingested",
        version_id=str(version.id),
        status=version.status.value,
        chunks=len(rows),
        mappings=len(proposals),
    )
    return IngestResult(version.id, version.status, len(rows), len(proposals))


async def _activate(session: AsyncSession, version: DocumentVersion, document: Document) -> None:
    """Flip the document to this version unless a newer one is already live."""
    locked = await session.scalar(
        select(Document).where(Document.id == document.id).with_for_update()
    )
    assert locked is not None
    current = (
        await session.get(DocumentVersion, locked.active_version_id)
        if locked.active_version_id
        else None
    )
    if current is not None and current.id != version.id:
        if current.version > version.version:
            version.status = DocumentVersionStatus.SUPERSEDED
            return
        current.status = DocumentVersionStatus.SUPERSEDED
    locked.active_version_id = version.id
    version.status = DocumentVersionStatus.ACTIVE
    version.activated_at = datetime.now(UTC)


async def run_ingestion_job(
    sessionmaker: async_sessionmaker[AsyncSession],
    store: ObjectStore,
    version_id: uuid.UUID,
    *,
    ocr: OcrProvider | None = None,
) -> IngestResult:
    """Job entry point: opens a session, resolves providers from settings, runs the pipeline."""
    async with sessionmaker() as session:
        owner = await session.scalar(
            select(Document.user_id)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .where(DocumentVersion.id == version_id)
        )
        if owner is None:
            raise KnowledgeError(f"unknown document version {version_id}")
        try:
            async with (
                embedder_scope(usage_context(owner, version_id, "embed")) as embedder,
                mapper_scope() as mapper,
            ):
                return await run_ingestion(
                    session, version_id, store=store, embedder=embedder, mapper=mapper, ocr=ocr
                )
        except ProviderNotConfiguredError as exc:
            await session.rollback()
            await _mark_failed(session, version_id, _describe(exc))
            return IngestResult(version_id, DocumentVersionStatus.FAILED, detail=_describe(exc))
