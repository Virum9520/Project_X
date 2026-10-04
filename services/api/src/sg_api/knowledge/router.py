"""Learner document API: upload, version, inspect, review concept mappings, delete.

    POST   /v1/documents                         upload a file (new document, or a new version
                                                 when `document_id` is given); 202, ingestion
                                                 runs as a Hatchet job
    GET    /v1/documents                         the learner's documents with version status
    GET    /v1/documents/{id}                    one document
    DELETE /v1/documents/{id}                    delete it and purge its text and originals
    POST   /v1/documents/{id}/versions/{vid}/retry  re-run a failed ingestion
    GET    /v1/documents/{id}/mappings           concept mappings proposed for the active version
    PATCH  /v1/documents/mappings/{mapping_id}   approve or reject a proposed mapping

Auth is the learner's Clerk session; every query is scoped to that learner. An uploaded file is
stored as an opaque blob and read only by the worker. Its text is never executed or trusted.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sg_api.knowledge.deps import (
    IngestDispatcher,
    current_user_id,
    get_ingest_dispatcher,
    get_object_store,
    max_upload_bytes,
)
from sg_core.db import session_scope
from sg_core.knowledge import (
    DocumentNotFound,
    UnsupportedDocumentError,
    delete_document,
    get_document,
    list_documents,
    list_mappings,
    review_mapping,
    store_upload,
    version_for_user,
)
from sg_core.knowledge.service import DocumentView, MappingView, VersionView
from sg_core.logging import get_logger
from sg_core.models.enums import DocumentKind, DocumentVersionStatus, ReviewStatus
from sg_core.providers import ObjectStore, ProviderError

router = APIRouter(prefix="/v1/documents", tags=["documents"])
log = get_logger(__name__)

UserId = Annotated[uuid.UUID, Depends(current_user_id)]
Db = Annotated[AsyncSession, Depends(session_scope)]
Store = Annotated[ObjectStore, Depends(get_object_store)]
Dispatcher = Annotated[IngestDispatcher, Depends(get_ingest_dispatcher)]
READ_CHUNK = 1024 * 1024


class VersionOut(BaseModel):
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

    @classmethod
    def of(cls, v: VersionView) -> "VersionOut":
        return cls(**{name: getattr(v, name) for name in cls.model_fields})


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    kind: DocumentKind
    created_at: datetime
    active_version_id: uuid.UUID | None
    versions: list[VersionOut]

    @classmethod
    def of(cls, d: DocumentView) -> "DocumentOut":
        return cls(
            id=d.id,
            title=d.title,
            kind=d.kind,
            created_at=d.created_at,
            active_version_id=d.active_version_id,
            versions=[VersionOut.of(v) for v in d.versions],
        )


class UploadOut(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    version: int
    status: DocumentVersionStatus
    duplicate: bool


class MappingOut(BaseModel):
    id: uuid.UUID
    concept_key: str
    concept_title: str
    chunk_ordinal: int | None
    confidence: float | None
    status: ReviewStatus
    method: str

    @classmethod
    def of(cls, m: MappingView) -> "MappingOut":
        return cls(**{name: getattr(m, name) for name in cls.model_fields})


class MappingReview(BaseModel):
    status: ReviewStatus


def _not_found(exc: DocumentNotFound) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "document not found")


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """Read an upload without ever holding more than `limit` bytes plus one chunk."""
    data = bytearray()
    while chunk := await file.read(READ_CHUNK):
        data += chunk
        if len(data) > limit:
            raise HTTPException(
                413,
                f"file is larger than {limit // (1024 * 1024)} MB",
            )
    return bytes(data)


async def _dispatch(dispatcher: IngestDispatcher, version_id: uuid.UUID) -> bool:
    try:
        await dispatcher.dispatch(version_id)
    except Exception:  # the upload is saved; the learner can retry processing
        log.warning("knowledge.dispatch_failed", version_id=str(version_id), exc_info=True)
        return False
    return True


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=UploadOut)
async def upload_document(
    user_id: UserId,
    session: Db,
    store: Store,
    dispatcher: Dispatcher,
    limit: Annotated[int, Depends(max_upload_bytes)],
    file: Annotated[UploadFile, File()],
    kind: Annotated[DocumentKind, Form()] = DocumentKind.STUDY_MATERIAL,
    title: Annotated[str | None, Form(max_length=300)] = None,
    document_id: Annotated[uuid.UUID | None, Form()] = None,
) -> UploadOut:
    data = await _read_limited(file, limit)
    try:
        result = await store_upload(
            session,
            store,
            user_id=user_id,
            data=data,
            filename=file.filename,
            declared_mime=file.content_type,
            kind=kind,
            title=title,
            document_id=document_id,
            max_bytes=limit,
        )
    except UnsupportedDocumentError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    except DocumentNotFound as exc:
        raise _not_found(exc) from exc
    except ProviderError as exc:
        log.warning("knowledge.store_failed", error=str(exc)[:200])
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "storage is unavailable") from exc
    await session.commit()
    if result.needs_ingestion:
        await _dispatch(dispatcher, result.version_id)
    return UploadOut(
        document_id=result.document_id,
        version_id=result.version_id,
        version=result.version,
        status=result.status,
        duplicate=result.duplicate,
    )


@router.get("", response_model=list[DocumentOut])
async def documents(user_id: UserId, session: Db) -> list[DocumentOut]:
    return [DocumentOut.of(d) for d in await list_documents(session, user_id)]


@router.patch("/mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def review_concept_mapping(
    mapping_id: uuid.UUID, body: MappingReview, user_id: UserId, session: Db
) -> Response:
    try:
        await review_mapping(session, user_id, mapping_id, body.status)
    except DocumentNotFound as exc:
        raise _not_found(exc) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{document_id}", response_model=DocumentOut)
async def document(document_id: uuid.UUID, user_id: UserId, session: Db) -> DocumentOut:
    try:
        return DocumentOut.of(await get_document(session, user_id, document_id))
    except DocumentNotFound as exc:
        raise _not_found(exc) from exc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_document(
    document_id: uuid.UUID, user_id: UserId, session: Db, store: Store
) -> Response:
    try:
        await delete_document(session, store, user_id, document_id)
    except DocumentNotFound as exc:
        raise _not_found(exc) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{document_id}/versions/{version_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UploadOut,
)
async def retry_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    user_id: UserId,
    session: Db,
    dispatcher: Dispatcher,
) -> UploadOut:
    try:
        version = await version_for_user(session, user_id, document_id, version_id)
    except DocumentNotFound as exc:
        raise _not_found(exc) from exc
    if version.status is not DocumentVersionStatus.FAILED and (
        version.status is not DocumentVersionStatus.UPLOADED
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, f"version is {version.status.value}")
    version.status = DocumentVersionStatus.UPLOADED
    version.error = None
    await session.commit()
    await _dispatch(dispatcher, version.id)
    return UploadOut(
        document_id=document_id,
        version_id=version.id,
        version=version.version,
        status=version.status,
        duplicate=False,
    )


@router.get("/{document_id}/mappings", response_model=list[MappingOut])
async def concept_mappings(
    document_id: uuid.UUID, user_id: UserId, session: Db
) -> list[MappingOut]:
    try:
        return [MappingOut.of(m) for m in await list_mappings(session, user_id, document_id)]
    except DocumentNotFound as exc:
        raise _not_found(exc) from exc
