"""Dependencies shared by the document routes and the `search_my_documents` tool.

Each is a seam tests replace through `app.dependency_overrides`.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from sg_api.sessions.identity import Learner, current_learner
from sg_core.db import session_scope
from sg_core.knowledge.providers import embedder_scope
from sg_core.knowledge.service import resolve_user_id
from sg_core.memory.embeddings import EmbeddingProvider
from sg_core.providers import ObjectStore, ProviderNotConfiguredError, object_store_from_settings
from sg_core.settings import Settings, get_settings


class IngestDispatcher(Protocol):
    async def dispatch(self, document_version_id: uuid.UUID) -> None: ...


def get_object_store(request: Request) -> ObjectStore:
    store: ObjectStore | None = getattr(request.app.state, "object_store", None)
    if store is None:
        try:
            store = request.app.state.object_store = object_store_from_settings()
        except ProviderNotConfiguredError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "document storage is not configured"
            ) from exc
    return store


def get_ingest_dispatcher(request: Request) -> IngestDispatcher:
    dispatcher: IngestDispatcher | None = getattr(request.app.state, "ingest_dispatcher", None)
    if dispatcher is None:
        from sg_worker.dispatch import HatchetIngestDispatcher

        dispatcher = request.app.state.ingest_dispatcher = HatchetIngestDispatcher()
    return dispatcher


async def get_embedder() -> AsyncIterator[EmbeddingProvider]:
    try:
        async with embedder_scope() as embedder:
            yield embedder
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "search is not configured"
        ) from exc


async def current_user_id(
    learner: Annotated[Learner, Depends(current_learner)],
    session: Annotated[AsyncSession, Depends(session_scope)],
) -> uuid.UUID:
    """`users.id` of the signed-in learner (the mirror row is created by `GET /v1/me`)."""
    user_id = await resolve_user_id(session, learner.user_id)
    if user_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "finish onboarding before uploading documents"
        )
    return user_id


def max_upload_bytes(settings: Annotated[Settings, Depends(get_settings)]) -> int:
    return settings.max_upload_bytes


__all__ = [
    "IngestDispatcher",
    "current_user_id",
    "get_embedder",
    "get_ingest_dispatcher",
    "get_object_store",
    "max_upload_bytes",
    "resolve_user_id",
]
