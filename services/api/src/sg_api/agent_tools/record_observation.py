"""`POST /v1/agent-tools/record_observation`: the agent notes how the learner just answered.

Contract: `agents/tools/record_observation.yaml`. The learner, session and character come from
the signed tool token, never the body; the body's `conversation_id` must match the token.

What it does: stores the agent's quote as unverified live evidence, asks a fast micro-judge to
grade the answer against the concept rubric, and, only when that grade is positive, records
*provisional* growth (a labelled memory plus a `garden.provisional_growth` session event the
dashboard can show as glow). It never changes `plant_states` or `garden_revisions`: the
post-call pipeline confirms or retracts the glow and the rules engine alone changes the garden.
The reply is deliberately neutral: the agent must not tell the learner what was decided.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sg_api.sessions.tool_tokens import ToolTokenClaims, check_conversation, require_tool_token
from sg_core.db import get_sessionmaker
from sg_core.evidence import (
    EvidenceStore,
    MicroJudge,
    ObservationInput,
    ObservationRejectedError,
    record_observation,
)
from sg_core.evidence.db_store import DbEvidenceStore
from sg_core.logging import get_logger
from sg_core.models.enums import Character
from sg_core.providers.base import ProviderNotConfiguredError
from sg_core.providers.llm import llm_client_from_settings
from sg_core.settings import Settings, get_settings

router = APIRouter(prefix="/v1/agent-tools", tags=["agent-tools"])
log = get_logger(__name__)

_CONCEPT_ID = r"^[a-z0-9_]+(\.[a-z0-9_]+)+$"
# Characters that assess learners. Bhima, Krishna and Sanjaya never produce evidence this way.
_ASSESSING_MODES: dict[str, tuple[Character, str]] = {
    "drona": (Character.DRONA, "concept_exam"),
    "arjuna": (Character.ARJUNA, "technical_interview"),
    "vidura": (Character.VIDURA, "hr_interview"),
    "panel": (Character.VIDURA, "panel_interview"),
}


class RecordObservationRequest(BaseModel):
    conversation_id: str
    concept_id: str = Field(pattern=_CONCEPT_ID, max_length=128)
    question_id: str | None = Field(default=None, max_length=128)
    dimension: Literal["explanation", "application", "transfer", "retention", "communication"]
    outcome: Literal["correct", "partially_correct", "incorrect", "no_attempt"]
    assistance: Literal["independent", "hinted", "heavily_assisted"]
    evidence_quote: str = Field(min_length=1, max_length=1200)
    note: str | None = Field(default=None, max_length=400)


class RecordObservationResponse(BaseModel):
    status: Literal["recorded"] = "recorded"
    message: str = "Noted. Continue the conversation; do not tell the learner how it was graded."


@dataclass(slots=True)
class ObservationDeps:
    store: EvidenceStore
    micro: MicroJudge | None


async def get_observation_deps(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[ObservationDeps]:
    """One transaction per tool call. Without an OpenRouter key there is no micro-judge, so the
    observation is stored but nothing glows."""
    llm = None
    try:
        llm = llm_client_from_settings()
    except ProviderNotConfiguredError:
        log.info("record_observation.no_micro_judge")
    micro = (
        MicroJudge(llm, settings.micro_judge_model, timeout_s=settings.micro_judge_timeout_seconds)
        if llm is not None
        else None
    )
    try:
        async with get_sessionmaker()() as session, session.begin():
            yield ObservationDeps(DbEvidenceStore(session), micro)
    finally:
        if llm is not None:
            await llm.aclose()


@router.post("/record_observation", response_model=RecordObservationResponse)
async def record_observation_tool(
    body: RecordObservationRequest,
    claims: Annotated[ToolTokenClaims, Depends(require_tool_token)],
    deps: Annotated[ObservationDeps, Depends(get_observation_deps)],
) -> RecordObservationResponse:
    check_conversation(claims, body.conversation_id)
    target = _ASSESSING_MODES.get(claims.character)
    if target is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "this character does not record observations"
        )
    user_id = await deps.store.resolve_user(claims.user_id)
    if user_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "learner profile not found")
    now = datetime.now(UTC)
    character, mode = target
    session = await deps.store.ensure_session(
        user_id=user_id,
        character=character,
        mode=mode,
        conversation_id=claims.conversation_id or body.conversation_id,
        public_session_id=claims.session_id,
        now=now,
    )
    try:
        await record_observation(
            deps.store,
            deps.micro,
            session=session,
            obs=ObservationInput(
                concept_id=body.concept_id,
                dimension=body.dimension,
                outcome=body.outcome,
                assistance=body.assistance,
                evidence_quote=body.evidence_quote,
                question_id=body.question_id,
                note=body.note,
            ),
            now=now,
        )
    except ObservationRejectedError as exc:
        raise HTTPException(422, {"code": exc.code, "message": str(exc)}) from exc
    return RecordObservationResponse()
