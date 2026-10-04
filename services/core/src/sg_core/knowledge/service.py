"""Document storage and management: upload, versioning, listing, mapping review, deletion.

Every function takes the owner's `users.id` and scopes every query by it: a document that belongs
to someone else is reported as not found. The functions flush but do not commit; the caller (API
route, worker task) owns the transaction so it can dispatch the ingestion job only after commit.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.knowledge.errors import DocumentNotFound, UnsupportedDocumentError
from sg_core.knowledge.extract import detect_mime_type
from sg_core.models.curriculum import Concept
from sg_core.models.enums import DocumentKind, DocumentVersionStatus, ReviewStatus
from sg_core.models.identity import User
from sg_core.models.knowledge import Chunk, ConceptMapping, Document, DocumentVersion
from sg_core.providers.storage import ObjectStore

DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
RETRYABLE_STATUSES = frozenset({DocumentVersionStatus.UPLOADED, DocumentVersionStatus.FAILED})


@dataclass(frozen=True, slots=True)
class UploadResult:
    document_id: uuid.UUID
    version_id: uuid.UUID
    version: int
    status: DocumentVersionStatus
    duplicate: bool  # the same bytes were already uploaded for this document
    needs_ingestion: bool  # the caller should dispatch the ingestion job after commit


@dataclass(frozen=True, slots=True)
class VersionView:
    id: uuid.UUID
    version: int
    status: DocumentVersionStatus
    page_count: int | None
    byte_size: int | None
    original_filename: str | None
    extraction_flags: dict[str, Any]
    error: str | None
    created_at: datetime
    activated_at: datetime | None


@dataclass(frozen=True, slots=True)
class DocumentView:
    id: uuid.UUID
    title: str
    kind: DocumentKind
    created_at: datetime
    active_version_id: uuid.UUID | None
    versions: list[VersionView]


@dataclass(frozen=True, slots=True)
class MappingView:
    id: uuid.UUID
    concept_key: str
    concept_title: str
    chunk_ordinal: int | None
    confidence: float | None
    status: ReviewStatus
    method: str


async def resolve_user_id(session: AsyncSession, clerk_user_id: str) -> uuid.UUID | None:
    """Map the Clerk user ID (the identity in sessions and tool tokens) to `users.id`."""
    return await session.scalar(
        select(User.id).where(User.clerk_user_id == clerk_user_id, User.deleted_at.is_(None))
    )


def default_title(filename: str | None) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", (filename or "").strip())
    stem = " ".join(re.sub(r"[\x00-\x1f\x7f/\\]", " ", stem).split())
    return (stem or "Untitled document")[:300]


async def store_upload(
    session: AsyncSession,
    store: ObjectStore,
    *,
    user_id: uuid.UUID,
    data: bytes,
    filename: str | None,
    declared_mime: str | None,
    kind: DocumentKind = DocumentKind.STUDY_MATERIAL,
    title: str | None = None,
    document_id: uuid.UUID | None = None,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> UploadResult:
    """Persist an upload as a new document, or as a new version of `document_id`.

    The original goes to the object store under a key owned by this learner. Re-uploading
    identical bytes to the same document is a no-op that returns the existing version (and asks
    for ingestion again only if that version never finished).
    """
    if not data:
        raise UnsupportedDocumentError("the file is empty")
    if len(data) > max_bytes:
        raise UnsupportedDocumentError(f"file is larger than {max_bytes // (1024 * 1024)} MB")
    mime = detect_mime_type(filename, declared_mime, data)
    content_hash = hashlib.sha256(data).hexdigest()

    if document_id is not None:
        document = await session.scalar(
            select(Document)
            .where(
                Document.id == document_id,
                Document.user_id == user_id,
                Document.deleted_at.is_(None),
            )
            .with_for_update()  # serialises concurrent version numbering
        )
        if document is None:
            raise DocumentNotFound(str(document_id))
        existing = await session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.content_hash == content_hash,
            )
        )
        if existing is not None:
            retry = existing.status in RETRYABLE_STATUSES
            if existing.status is DocumentVersionStatus.FAILED:
                existing.status = DocumentVersionStatus.UPLOADED
                existing.error = None
            return UploadResult(
                document.id, existing.id, existing.version, existing.status, True, retry
            )
    else:
        document = Document(
            user_id=user_id, kind=kind, title=(title or default_title(filename))[:300]
        )
        session.add(document)
        await session.flush()

    next_version = (
        await session.scalar(
            select(func.coalesce(func.max(DocumentVersion.version), 0)).where(
                DocumentVersion.document_id == document.id
            )
        )
        or 0
    ) + 1
    storage_key = f"users/{user_id}/documents/{document.id}/v{next_version}-{content_hash[:16]}"
    await store.put(storage_key, data, content_type=mime)
    version = DocumentVersion(
        document_id=document.id,
        version=next_version,
        content_hash=content_hash,
        storage_key=storage_key,
        original_filename=filename[:300] if filename else None,
        mime_type=mime,
        byte_size=len(data),
        status=DocumentVersionStatus.UPLOADED,
    )
    session.add(version)
    await session.flush()
    return UploadResult(
        document.id, version.id, next_version, DocumentVersionStatus.UPLOADED, False, True
    )


async def _owned_document(
    session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == user_id,
            Document.deleted_at.is_(None),
        )
    )
    if document is None:
        raise DocumentNotFound(str(document_id))
    return document


def _version_view(v: DocumentVersion) -> VersionView:
    return VersionView(
        id=v.id,
        version=v.version,
        status=v.status,
        page_count=v.page_count,
        byte_size=v.byte_size,
        original_filename=v.original_filename,
        extraction_flags=dict(v.extraction_flags or {}),
        error=v.error,
        created_at=v.created_at,
        activated_at=v.activated_at,
    )


async def list_documents(session: AsyncSession, user_id: uuid.UUID) -> list[DocumentView]:
    documents = (
        await session.scalars(
            select(Document)
            .where(Document.user_id == user_id, Document.deleted_at.is_(None))
            .order_by(Document.created_at.desc())
        )
    ).all()
    if not documents:
        return []
    versions = (
        await session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id.in_([d.id for d in documents]))
            .order_by(DocumentVersion.version.desc())
        )
    ).all()
    by_document: dict[uuid.UUID, list[VersionView]] = {}
    for v in versions:
        by_document.setdefault(v.document_id, []).append(_version_view(v))
    return [
        DocumentView(
            d.id, d.title, d.kind, d.created_at, d.active_version_id, by_document.get(d.id, [])
        )
        for d in documents
    ]


async def get_document(
    session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID
) -> DocumentView:
    document = await _owned_document(session, user_id, document_id)
    versions = (
        await session.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version.desc())
        )
    ).all()
    return DocumentView(
        document.id,
        document.title,
        document.kind,
        document.created_at,
        document.active_version_id,
        [_version_view(v) for v in versions],
    )


async def version_for_user(
    session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID, version_id: uuid.UUID
) -> DocumentVersion:
    await _owned_document(session, user_id, document_id)
    version = await session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id, DocumentVersion.document_id == document_id
        )
    )
    if version is None:
        raise DocumentNotFound(str(version_id))
    return version


async def delete_document(
    session: AsyncSession, store: ObjectStore, user_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    """Soft-delete a document and purge its searchable text and stored originals.

    Version rows stay (sessions and assessments may cite a version) but nothing readable remains.
    """
    document = await _owned_document(session, user_id, document_id)
    versions = (
        await session.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == document.id)
        )
    ).all()
    version_ids = [v.id for v in versions]
    if version_ids:
        await session.execute(delete(Chunk).where(Chunk.document_version_id.in_(version_ids)))
    document.deleted_at = datetime.now(UTC)
    document.active_version_id = None
    await session.flush()
    for version in versions:
        await store.delete(version.storage_key)


async def list_mappings(
    session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID
) -> list[MappingView]:
    """Concept mappings proposed for the document's active version."""
    document = await _owned_document(session, user_id, document_id)
    if document.active_version_id is None:
        return []
    rows = await session.execute(
        select(ConceptMapping, Concept, Chunk.ordinal)
        .join(Concept, Concept.id == ConceptMapping.concept_id)
        .outerjoin(Chunk, Chunk.id == ConceptMapping.chunk_id)
        .where(ConceptMapping.document_version_id == document.active_version_id)
        .order_by(Concept.key, Chunk.ordinal)
    )
    return [
        MappingView(m.id, c.key, c.title, ordinal, m.confidence, m.status, m.method)
        for m, c, ordinal in rows.all()
    ]


async def review_mapping(
    session: AsyncSession, user_id: uuid.UUID, mapping_id: uuid.UUID, status: ReviewStatus
) -> None:
    """Approve or reject a proposed mapping. Only the owner's own documents are reachable."""
    owned = (
        select(DocumentVersion.id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.user_id == user_id, Document.deleted_at.is_(None))
    )
    result = await session.execute(
        update(ConceptMapping)
        .where(ConceptMapping.id == mapping_id, ConceptMapping.document_version_id.in_(owned))
        .values(status=status)
    )
    if result.rowcount == 0:  # type: ignore[attr-defined]
        raise DocumentNotFound(str(mapping_id))
