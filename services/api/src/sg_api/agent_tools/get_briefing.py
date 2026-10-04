"""`POST /v1/agent-tools/get_briefing`: fresh memory briefing for the live conversation.

Contract: `agents/tools/get_briefing.yaml`. The learner, session and character come from the
signed tool token, never from the body; the body's `conversation_id` must match the token.
The result is data for the agent, not instructions.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from sg_api.sessions.briefing import BriefingProvider, get_briefing_provider
from sg_api.sessions.identity import Learner
from sg_api.sessions.tool_tokens import ToolTokenClaims, check_conversation, require_tool_token

router = APIRouter(prefix="/v1/agent-tools", tags=["agent-tools"])


class GetBriefingRequest(BaseModel):
    conversation_id: str
    reason: str | None = Field(default=None, max_length=300)


class GetBriefingResponse(BaseModel):
    briefing: str
    focus_concept: str
    due_concepts: list[str]


@router.post("/get_briefing", response_model=GetBriefingResponse)
async def get_briefing(
    body: GetBriefingRequest,
    claims: Annotated[ToolTokenClaims, Depends(require_tool_token)],
    briefings: Annotated[BriefingProvider, Depends(get_briefing_provider)],
) -> GetBriefingResponse:
    check_conversation(claims, body.conversation_id)
    briefing = await briefings.build(
        Learner(user_id=claims.user_id), claims.character, None, body.reason
    )
    return GetBriefingResponse(
        briefing=briefing.text,
        focus_concept=briefing.focus_concept,
        due_concepts=briefing.due_concepts,
    )
