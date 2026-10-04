"""`POST /v1/agent-tools/query_my_analytics`: the learner's analytics for a live conversation.

Contract: `agents/tools/query_my_analytics.yaml`. The learner comes from the signed tool token,
never from the body. Results carry `citations` (evidence ids) and are data for the agent, not
instructions: quotes inside them are the learner's words.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from sg_api.garden.analytics import AnalyticsError, make_query
from sg_api.garden.router import analytics_http_error
from sg_api.garden.schemas import AnalyticsOut
from sg_api.garden.service import GardenService, get_garden_service
from sg_api.sessions.tool_tokens import ToolTokenClaims, check_conversation, require_tool_token

router = APIRouter(prefix="/v1/agent-tools", tags=["agent-tools"])

Metric = Literal[
    "readiness",
    "stage_counts",
    "weakest_concepts",
    "reviews_due",
    "misconceptions",
    "recent_changes",
    "concept_detail",
    "practice_time",
    "independence_ratio",
]


class QueryAnalyticsRequest(BaseModel):
    conversation_id: str
    metric: Metric
    domain: str | None = Field(default=None, max_length=64)
    concept_id: str | None = Field(default=None, max_length=128)
    date_from: str | None = Field(default=None, max_length=32)
    date_to: str | None = Field(default=None, max_length=32)


@router.post("/query_my_analytics", response_model=AnalyticsOut)
async def query_my_analytics(
    body: QueryAnalyticsRequest,
    claims: Annotated[ToolTokenClaims, Depends(require_tool_token)],
    service: Annotated[GardenService, Depends(get_garden_service)],
) -> AnalyticsOut:
    check_conversation(claims, body.conversation_id)
    try:
        query = make_query(body.domain, body.concept_id, body.date_from, body.date_to)
        return await service.analytics(claims.user_id, body.metric, query)
    except AnalyticsError as exc:
        analytics_http_error(exc)
