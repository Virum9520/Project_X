"""POST /v1/sessions: start a voice session with a Skill Garden character.

Returns everything the browser needs for `useConversation().startSession(...)`:
a WebRTC conversation token for the private agent, the dynamic variables (briefing, learner
context and the server-tool token) and the session ID.

The `sessions` row is persisted here (C12): character, mode, agent, ElevenLabs conversation ID,
the active curriculum and `document_version_id` (the learner's newest active document version,
pinned so the judge later reads the same material).

Pending: C03 budget reservation before minting a token.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sg_api.drona.store import DEFAULT_MODE, NewSession, SessionStore, get_session_store
from sg_api.sessions.briefing import BriefingProvider, get_briefing_provider
from sg_api.sessions.identity import Learner, current_learner
from sg_api.sessions.tool_tokens import mint_tool_token
from sg_core.logging import get_logger
from sg_core.providers.elevenlabs import ElevenLabsClient, ElevenLabsError, client_from_settings
from sg_core.settings import Environment, Settings, get_settings

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])
log = get_logger(__name__)

# Learner-facing agents; the owner assistant is started from the admin API instead.
SessionCharacter = Literal["drona", "arjuna", "vidura", "panel", "bhima", "krishna", "sanjaya"]


class SessionStartRequest(BaseModel):
    character: SessionCharacter
    focus_concept_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
    persona_tone: Literal["energetic", "calm"] = "calm"
    # Drona only: `teach_back` starts the learner in the explain-it-to-me phase's UI mode.
    mode: Literal["concept_exam", "teach_back"] | None = None


class SessionStartResponse(BaseModel):
    session_id: str
    character: SessionCharacter
    agent_id: str
    conversation_id: str | None
    conversation_token: str
    # Pass as `dynamicVariables` to startSession. Contains the server-tool token: keep it in
    # memory only and never log it.
    dynamic_variables: dict[str, str]
    tool_token_expires_at: datetime
    # False when the learner has no `users` row yet: the call works but leaves no records.
    persisted: bool = True


async def get_elevenlabs() -> AsyncIterator[ElevenLabsClient]:
    try:
        client = client_from_settings()
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    async with client:
        yield client


def _local_time(timezone: str, now: datetime) -> str:
    try:
        local = now.astimezone(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        local = now
    return local.strftime("%A %-I:%M %p")


@router.post("", response_model=SessionStartResponse, status_code=status.HTTP_201_CREATED)
async def start_session(
    body: SessionStartRequest,
    learner: Annotated[Learner, Depends(current_learner)],
    settings: Annotated[Settings, Depends(get_settings)],
    briefings: Annotated[BriefingProvider, Depends(get_briefing_provider)],
    elevenlabs: Annotated[ElevenLabsClient, Depends(get_elevenlabs)],
    store: Annotated[SessionStore | None, Depends(get_session_store)] = None,
) -> SessionStartResponse:
    agent_id = settings.elevenlabs_agent_ids.get(body.character)
    if not agent_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"no ElevenLabs agent configured for {body.character}",
        )

    # Other routers (C18's accept-call) call this function directly, without dependencies.
    store = store or get_session_store()
    session_uuid = uuid.uuid4()
    session_id = str(session_uuid)
    briefing = await briefings.build(learner, body.character, body.focus_concept_id)

    try:
        token = await elevenlabs.get_conversation_token(agent_id, participant_name=session_id)
    except ElevenLabsError as exc:
        log.warning("sessions.token_failed", character=body.character, status=exc.status_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "voice provider unavailable") from exc

    tool_token, expires_at = mint_tool_token(
        user_id=learner.user_id,
        session_id=session_id,
        character=body.character,
        conversation_id=token.conversation_id,
        settings=settings,
    )
    mode = body.mode if body.character == "drona" and body.mode else DEFAULT_MODE[body.character]
    persisted = False
    try:
        persisted = await store.create(
            NewSession(
                clerk_user_id=learner.user_id,
                session_id=session_uuid,
                character=body.character,
                mode=mode,
                agent_id=agent_id,
                conversation_id=token.conversation_id,
                focus_concept=body.focus_concept_id,
            )
        )
    except Exception as exc:
        log.warning("sessions.persist_failed", session_id=session_id, exc_info=True)
        if settings.environment not in (Environment.LOCAL, Environment.TEST):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "could not record the session"
            ) from exc
    now = datetime.now(UTC)
    dynamic_variables = {
        "learner_name": learner.display_name,
        "session_id": session_id,
        "briefing": briefing.text,
        "focus_concept": briefing.focus_concept,
        "focus_concept_title": briefing.focus_concept_title,
        "due_concepts": ", ".join(briefing.due_concepts) or "none",
        "target_role": briefing.target_role,
        "persona_tone": body.persona_tone,
        "local_time": _local_time(learner.timezone, now),
        # Bhima's retention question (C18 overrides these on accepted calls); "none" skips it.
        "retention_concept": "none",
        "retention_concept_title": "none",
        # Arjuna's plan and language (`POST /v1/arjuna/sessions` overrides these); "none" elsewhere.
        "interview_plan": "none",
        "preferred_language": "none",
        "secret__sg_tool_token": tool_token,
    }
    log.info(
        "sessions.started",
        session_id=session_id,
        character=body.character,
        agent_id=agent_id,
        conversation_id=token.conversation_id,
    )
    return SessionStartResponse(
        session_id=session_id,
        character=body.character,
        agent_id=agent_id,
        conversation_id=token.conversation_id,
        conversation_token=token.token,
        dynamic_variables=dynamic_variables,
        tool_token_expires_at=datetime.fromtimestamp(expires_at, UTC),
        persisted=persisted,
    )
