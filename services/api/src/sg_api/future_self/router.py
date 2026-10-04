"""Future-Self voice routes (C19): consent flow, record, revoke, daily message.

Flow: `POST /consent/challenge` -> the learner reads the phrase aloud in the browser ->
`POST /consent/recording` (raw audio body, challenge and acceptance in headers; no multipart
dependency) -> Scribe check -> Instant Voice Clone. `DELETE /consent` revokes everything.
All routes need a Clerk session (dev headers only in local/test, as for sessions).
"""

import base64
import uuid
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from sg_api.sessions.briefing import BriefingProvider, get_briefing_provider
from sg_api.sessions.identity import Learner, current_learner
from sg_api.sessions.router import get_elevenlabs
from sg_core.db import get_sessionmaker
from sg_core.economics.budget import (
    BudgetExceededError,
    budget_hold,
    budget_key_for,
    monthly_limit_usd,
)
from sg_core.logging import get_logger
from sg_core.models.enums import CostCenter
from sg_core.models.identity import User
from sg_core.providers.base import ProviderNotConfiguredError
from sg_core.providers.elevenlabs import ElevenLabsClient
from sg_core.providers.llm import LLMClient, llm_client_from_settings
from sg_core.providers.storage import ObjectStore, object_store_from_settings
from sg_core.settings import Settings, get_settings
from sg_core.voice_clone import (
    CONSENT_STATEMENTS,
    CONSENT_VERSION,
    ConsentRecord,
    ConsentStore,
    DbConsentStore,
    FutureSelfVoice,
    VoiceCloneError,
)

router = APIRouter(prefix="/v1/future-self", tags=["future-self"])
log = get_logger(__name__)

MESSAGE_ESTIMATE_USD = Decimal("0.05")
# Raw recording body cap (the service enforces the same limit; this stops reading early).
MAX_BODY_BYTES = 8 * 1024 * 1024

_STATUS_FOR_CODE = {
    "consent_required": status.HTTP_403_FORBIDDEN,
    "already_consented": status.HTTP_409_CONFLICT,
    "invalid_recording": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "invalid_challenge": status.HTTP_400_BAD_REQUEST,
    "provider_unavailable": status.HTTP_502_BAD_GATEWAY,
}


class ConsentRecordOut(BaseModel):
    id: str
    consent_version: str
    created_at: datetime
    revoked_at: datetime | None
    voice_active: bool


class ConsentStatus(BaseModel):
    consent_version: str
    statements: list[str]
    active: bool
    current: ConsentRecordOut | None
    history: list[ConsentRecordOut]


class ChallengeOut(BaseModel):
    phrase: str
    challenge_token: str
    expires_at: datetime
    consent_version: str
    statements: list[str]


class RecordingResult(BaseModel):
    verified: bool
    similarity: float
    words_heard: bool
    transcript: str
    status: ConsentStatus


class MessageOut(BaseModel):
    script: str
    audio_base64: str
    media_type: str


def _out(record: ConsentRecord) -> ConsentRecordOut:
    return ConsentRecordOut(
        id=str(record.id),
        consent_version=record.consent_ver,
        created_at=record.created_at,
        revoked_at=record.revoked_at,
        voice_active=record.active,
    )


def _status(current: ConsentRecord | None, history: list[ConsentRecord]) -> ConsentStatus:
    return ConsentStatus(
        consent_version=CONSENT_VERSION,
        statements=list(CONSENT_STATEMENTS),
        active=current is not None and current.active,
        current=_out(current) if current else None,
        history=[_out(r) for r in history],
    )


# --- dependencies (each is overridden in tests) -------------------------------------------------


async def get_user_uuid(learner: Annotated[Learner, Depends(current_learner)]) -> uuid.UUID:
    """`users.id` for the signed-in Clerk user (filled by `/v1/me` or onboarding sync)."""
    try:
        async with get_sessionmaker()() as session:
            found = await session.scalar(
                select(User.id).where(
                    User.clerk_user_id == learner.user_id, User.deleted_at.is_(None)
                )
            )
    except Exception as exc:
        log.warning("future_self.user_lookup_failed", exc_info=True)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable") from exc
    if found is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "profile not ready; open your account first")
    return found


def get_consent_store() -> ConsentStore:
    return DbConsentStore()


def get_object_store() -> ObjectStore:
    try:
        return object_store_from_settings()
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


async def get_llm() -> AsyncIterator[LLMClient | None]:
    try:
        client = llm_client_from_settings()
    except ProviderNotConfiguredError:
        yield None
        return
    async with client:
        yield client


def get_voice_service(
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[ConsentStore, Depends(get_consent_store)],
    objects: Annotated[ObjectStore, Depends(get_object_store)],
    elevenlabs: Annotated[ElevenLabsClient, Depends(get_elevenlabs)],
    llm: Annotated[LLMClient | None, Depends(get_llm)],
) -> FutureSelfVoice:
    if settings.agent_tool_token_secret is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "consent signing not configured")

    def budget(user_id: uuid.UUID) -> AbstractAsyncContextManager[object]:
        return budget_hold(
            budget_key=budget_key_for(CostCenter.LEARNER, user_id),
            amount_usd=MESSAGE_ESTIMATE_USD,
            limit_usd=monthly_limit_usd(CostCenter.LEARNER, settings),
            cost_center=CostCenter.LEARNER,
            user_id=user_id,
        )

    return FutureSelfVoice(
        store=store,
        objects=objects,
        elevenlabs=elevenlabs,
        secret=settings.agent_tool_token_secret.get_secret_value().encode(),
        llm=llm,
        budget=budget,
    )


VoiceDep = Annotated[FutureSelfVoice, Depends(get_voice_service)]
UserDep = Annotated[uuid.UUID, Depends(get_user_uuid)]


def _http(exc: VoiceCloneError) -> HTTPException:
    return HTTPException(
        _STATUS_FOR_CODE.get(exc.code, status.HTTP_400_BAD_REQUEST),
        {"code": exc.code, "message": str(exc)},
    )


# --- routes -------------------------------------------------------------------------------------


@router.get("/consent", response_model=ConsentStatus)
async def consent_status(user_id: UserDep, voice: VoiceDep) -> ConsentStatus:
    current, history = await voice.status(user_id)
    return _status(current, history)


@router.post("/consent/challenge", response_model=ChallengeOut)
async def start_consent(user_id: UserDep, voice: VoiceDep) -> ChallengeOut:
    try:
        challenge = await voice.start(user_id)
    except VoiceCloneError as exc:
        raise _http(exc) from exc
    return ChallengeOut(
        phrase=challenge.phrase,
        challenge_token=challenge.token,
        expires_at=challenge.expires_at,
        consent_version=challenge.consent_version,
        statements=list(CONSENT_STATEMENTS),
    )


@router.post("/consent/recording", response_model=RecordingResult)
async def submit_recording(
    request: Request,
    user_id: UserDep,
    voice: VoiceDep,
    challenge_token: Annotated[str, Header(alias="X-Consent-Challenge")],
    accepted: Annotated[str, Header(alias="X-Consent-Accepted")] = "false",
) -> RecordingResult:
    """Body is the raw recording; `Content-Type` is its audio type."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "recording is too large")
        chunks.append(chunk)
    try:
        outcome = await voice.submit(
            user_id,
            challenge_token=challenge_token,
            audio=b"".join(chunks),
            content_type=request.headers.get("content-type", ""),
            accepted_statements=accepted.lower() == "true",
        )
    except VoiceCloneError as exc:
        raise _http(exc) from exc
    current, history = await voice.status(user_id)
    return RecordingResult(
        verified=outcome.verified,
        similarity=outcome.match.similarity,
        words_heard=outcome.match.words_heard,
        transcript=outcome.transcript,
        status=_status(current, history),
    )


@router.delete("/consent", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_consent(user_id: UserDep, voice: VoiceDep) -> Response:
    """One-tap revoke: deletes the voice at ElevenLabs and the recording here. Idempotent."""
    try:
        await voice.revoke(user_id)
    except VoiceCloneError as exc:
        raise _http(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/message", response_model=MessageOut)
async def todays_message(
    learner: Annotated[Learner, Depends(current_learner)],
    user_id: UserDep,
    voice: VoiceDep,
    briefings: Annotated[BriefingProvider, Depends(get_briefing_provider)],
) -> MessageOut:
    """Today's message from the learner's future self, in their own cloned voice."""
    briefing = await briefings.build(learner, "krishna", None, "goals and recent wins")
    try:
        message = await voice.speak_message(user_id, briefing.text)
    except BudgetExceededError as exc:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED, "monthly voice budget reached"
        ) from exc
    except VoiceCloneError as exc:
        raise _http(exc) from exc
    return MessageOut(
        script=message.script,
        audio_base64=base64.b64encode(message.audio.audio).decode(),
        media_type=message.audio.media_type,
    )
