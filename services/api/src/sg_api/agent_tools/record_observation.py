"""`POST /v1/agent-tools/record_observation`: one observation per assessed answer, mid-call.

Contract: `agents/tools/record_observation.yaml`. The agent's read is a signal, not a verdict: a
`MicroJudge` (C11) grades it quickly and the result becomes a provisional growth event on the
learner's live channel. Nothing permanent changes here; the post-call pipeline confirms or
retracts it. The response deliberately says nothing about the decision (the agent must never tell
the learner what was graded). The quote and note are learner-derived data and are flattened.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sg_api.agent_tools.fetch_question import CONCEPT_KEY
from sg_api.drona.growth import (
    GrowthFeed,
    MicroJudge,
    ObservationInput,
    ProvisionalVerdict,
    event_from_verdict,
    get_growth_feed,
    get_micro_judge,
)
from sg_api.drona.store import SessionStore, get_session_store
from sg_api.sessions.tool_tokens import ToolTokenClaims, check_conversation, require_tool_token
from sg_core.logging import get_logger

router = APIRouter(prefix="/v1/agent-tools", tags=["agent-tools"])
log = get_logger(__name__)


class RecordObservationRequest(BaseModel):
    conversation_id: str
    concept_id: str = Field(pattern=CONCEPT_KEY, max_length=128)
    question_id: str | None = Field(default=None, max_length=200)
    dimension: Literal["explanation", "application", "transfer", "retention", "communication"]
    outcome: Literal["correct", "partially_correct", "incorrect", "no_attempt"]
    assistance: Literal["independent", "hinted", "heavily_assisted"]
    evidence_quote: str = Field(max_length=1500)
    note: str | None = Field(default=None, max_length=1000)


class RecordObservationResponse(BaseModel):
    status: Literal["noted"] = "noted"


@router.post("/record_observation", response_model=RecordObservationResponse)
async def record_observation(
    body: RecordObservationRequest,
    claims: Annotated[ToolTokenClaims, Depends(require_tool_token)],
    store: Annotated[SessionStore, Depends(get_session_store)],
    judge: Annotated[MicroJudge, Depends(get_micro_judge)],
    feed: Annotated[GrowthFeed, Depends(get_growth_feed)],
) -> RecordObservationResponse:
    check_conversation(claims, body.conversation_id)
    try:
        rubric = await store.concept_rubric(body.concept_id)
    except Exception as exc:
        log.warning("record_observation.rubric_failed", exc_info=True)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "curriculum unavailable") from exc
    if rubric is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"unknown concept {body.concept_id}: use a curriculum ID"
        )
    observation = ObservationInput(
        concept_key=body.concept_id,
        dimension=body.dimension,
        outcome=body.outcome,
        assistance=body.assistance,
        evidence_quote=body.evidence_quote,
        note=body.note or "",
        question_id=body.question_id,
    )
    try:
        verdict = await judge.judge(observation, rubric)
    except Exception:
        # A judge outage must not break the call or invent growth: record a neutral note.
        log.warning("record_observation.judge_failed", exc_info=True)
        verdict = None
    if verdict is None:
        verdict = ProvisionalVerdict(
            outcome="unassessable",
            assisted=body.assistance != "independent",
            grows=False,
            judge="unavailable",
        )
    await feed.append(claims.user_id, event_from_verdict(claims.session_id, observation, verdict))
    log.info(
        "record_observation",
        session_id=claims.session_id,
        concept=body.concept_id,
        dimension=body.dimension,
        grows=verdict.grows,
    )
    return RecordObservationResponse()
