"""`/v1/recap/*`: the weekly Sanjaya recap (C20).

Learner routes need a Clerk session and only ever touch the caller's recaps. The one public route,
`GET /v1/recap/shared/{token}`, opens a recap through a signed private link the learner created
and can turn off.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from sg_api.garden.data import load_garden_data, resolve_user_id
from sg_api.recap.schemas import GenerateRecapIn, RecapOut, ShareOut
from sg_api.recap.service import (
    InvalidShareToken,
    RecapNotFound,
    RecapService,
)
from sg_api.sessions.identity import Learner, current_learner
from sg_core.db import get_sessionmaker
from sg_core.providers.base import ProviderNotConfiguredError
from sg_core.providers.elevenlabs import ElevenLabsClient, client_from_settings
from sg_core.providers.storage import object_store_from_settings
from sg_core.settings import get_settings

router = APIRouter(prefix="/v1/recap", tags=["recap"])

LearnerDep = Annotated[Learner, Depends(current_learner)]


async def get_recap_service() -> RecapService:
    settings = get_settings()
    try:
        store = object_store_from_settings()
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "recaps are not configured"
        ) from exc
    maker = get_sessionmaker()

    async def resolve(learner: str) -> uuid.UUID | None:
        async with maker() as session:
            return await resolve_user_id(session, learner)

    async def load(user_id: uuid.UUID, now: datetime):  # type: ignore[no-untyped-def]
        async with maker() as session:
            return await load_garden_data(session, user_id, now=now)

    speech: ElevenLabsClient | None
    try:
        speech = client_from_settings() if settings.sanjaya_voice_id else None
    except RuntimeError:
        speech = None
    secret = settings.agent_tool_token_secret
    return RecapService(
        resolve_user=resolve,
        load_data=load,
        store=store,
        speech=speech,
        voice_id=settings.sanjaya_voice_id,
        secret=secret.get_secret_value().encode() if secret else None,
    )


ServiceDep = Annotated[RecapService, Depends(get_recap_service)]


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "recap not found")


@router.post("/generate", response_model=RecapOut)
async def generate_recap(
    learner: LearnerDep, service: ServiceDep, body: GenerateRecapIn | None = None
) -> RecapOut:
    """Build (or return) this week's recap. Idempotent per learner and week unless `force`."""
    try:
        return await service.generate(learner.user_id, force=bool(body and body.force))
    except RecapNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/latest", response_model=RecapOut)
async def latest_recap(learner: LearnerDep, service: ServiceDep) -> RecapOut:
    try:
        return await service.get(learner.user_id)
    except RecapNotFound as exc:
        raise _not_found(exc) from exc


@router.get("/shared/{token}", response_model=RecapOut)
async def shared_recap(token: str, service: ServiceDep, response: Response) -> RecapOut:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    try:
        return await service.open_shared(token)
    except InvalidShareToken as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "this link is not valid") from exc


@router.get("/{week}", response_model=RecapOut)
async def get_recap(week: str, learner: LearnerDep, service: ServiceDep) -> RecapOut:
    try:
        return await service.get(learner.user_id, week)
    except RecapNotFound as exc:
        raise _not_found(exc) from exc


@router.post("/{week}/share", response_model=ShareOut)
async def share_recap(week: str, learner: LearnerDep, service: ServiceDep) -> ShareOut:
    try:
        token, expires = await service.share(learner.user_id, week, now=datetime.now(UTC))
    except RecapNotFound as exc:
        raise _not_found(exc) from exc
    except InvalidShareToken as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return ShareOut(token=token, path=f"/recap/shared/{token}", expires_at=expires.isoformat())


@router.delete("/{week}/share", status_code=status.HTTP_204_NO_CONTENT)
async def unshare_recap(week: str, learner: LearnerDep, service: ServiceDep) -> None:
    try:
        await service.unshare(learner.user_id, week)
    except RecapNotFound as exc:
        raise _not_found(exc) from exc
