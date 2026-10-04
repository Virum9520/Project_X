"""Owner assistant: `POST /v1/admin/assistant/ask`, `GET /v1/admin/assistant/status`.

Owner only: an admin session (allowlist or grant, verified email, second factor), the
`assistant.use` capability, and `principal.is_owner`. The assistant reads cost and usage data
through the MCP gateway, so granting `assistant.use` to another role is not enough on its own. Every
question is audited here and every tool call by the gateway.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from sg_api.auth import AdminPrincipal, admin_origin_guard, record_audit, require_capability
from sg_core.economics.budget import budget_key_for, committed_usd, monthly_limit_usd
from sg_core.identity import Capability
from sg_core.logging import get_logger
from sg_core.models.enums import CostCenter
from sg_core.providers.base import ProviderNotConfiguredError
from sg_core.settings import Settings, get_settings
from sg_mcp_gateway import CallContext, HistoryTurn, OwnerAssistant, build_assistant
from sg_mcp_gateway.assistant import AssistantAnswer, Basis, new_request_id
from sg_mcp_gateway.factory import limits_from_settings
from sg_mcp_gateway.gateway import ANALYTICS_QUERY, ELEVENLABS_READ_ONLY_TOOLS

log = get_logger(__name__)

MAX_CONCURRENT_QUESTIONS = 2

router = APIRouter(
    prefix="/v1/admin/assistant",
    tags=["owner-assistant"],
    dependencies=[Depends(admin_origin_guard)],
)


async def owner_only(
    principal: Annotated[AdminPrincipal, Depends(require_capability(Capability.ASSISTANT_USE))],
) -> AdminPrincipal:
    if not principal.is_owner:
        log.warning("assistant.denied", user_id=principal.user_id, reason="not_owner")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "the owner assistant is owner-only")
    return principal


OwnerDep = Annotated[AdminPrincipal, Depends(owner_only)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_assistant(request: Request, settings: SettingsDep) -> OwnerAssistant:
    assistant: OwnerAssistant | None = getattr(request.app.state, "owner_assistant", None)
    if assistant is None:
        try:
            assistant = build_assistant(settings, request.app.state.identity.audit)
        except ProviderNotConfiguredError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        request.app.state.owner_assistant = assistant
    return assistant


AssistantDep = Annotated[OwnerAssistant, Depends(get_assistant)]


class TurnIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[TurnIn] = Field(default_factory=list, max_length=12)


class ToolTraceOut(BaseModel):
    tool: str
    provider: str | None
    ok: bool
    rows: int | None
    truncated: bool
    duration_ms: int
    error: str | None


class AskResponse(BaseModel):
    request_id: str
    answer: str
    basis: Basis | None
    hypotheses: list[str]
    partial: bool
    unavailable_providers: dict[str, str]
    tools: list[ToolTraceOut]
    warnings: list[str]
    cost_usd: float
    steps: int
    model: str | None
    stopped: str | None
    generated_at: datetime


def _response(request_id: str, result: AssistantAnswer) -> AskResponse:
    return AskResponse(
        request_id=request_id,
        answer=result.answer,
        basis=result.basis,
        hypotheses=result.hypotheses,
        partial=result.partial,
        unavailable_providers=result.unavailable_providers,
        tools=[
            ToolTraceOut(
                tool=t.tool,
                provider=t.provider,
                ok=t.ok,
                rows=t.rows,
                truncated=t.truncated,
                duration_ms=t.duration_ms,
                error=t.error,
            )
            for t in result.tools
        ],
        warnings=result.warnings,
        cost_usd=float(result.cost_usd),
        steps=result.steps,
        model=result.model,
        stopped=result.stopped,
        generated_at=result.generated_at,
    )


def _slots(request: Request) -> asyncio.Semaphore:
    sem: asyncio.Semaphore | None = getattr(request.app.state, "assistant_slots", None)
    if sem is None:
        sem = asyncio.Semaphore(MAX_CONCURRENT_QUESTIONS)
        request.app.state.assistant_slots = sem
    return sem


@router.post("/ask", response_model=AskResponse)
async def ask(
    request: Request, body: AskRequest, principal: OwnerDep, assistant: AssistantDep
) -> AskResponse:
    request_id: str = getattr(request.state, "request_id", None) or new_request_id()
    base: dict[str, Any] = {
        "question": body.question[:500],
        "question_chars": len(body.question),
        "history_turns": len(body.history),
    }
    record_audit(request, action="assistant.ask", target=f"request:{request_id}", after=base)
    slots = _slots(request)
    if slots.locked():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many questions in flight")
    async with slots:
        ctx = CallContext(
            actor_id=principal.user_id,
            actor_email=principal.email,
            request_id=request_id,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        )
        result = await assistant.ask(
            ctx, body.question, [HistoryTurn(t.role, t.content) for t in body.history]
        )
    record_audit(
        request,
        action="assistant.ask",
        target=f"request:{request_id}",
        after={
            **base,
            "tool_calls": len(result.tools),
            "partial": result.partial,
            "stopped": result.stopped,
            "cost_usd": str(result.cost_usd),
            "steps": result.steps,
        },
    )
    return _response(request_id, result)


class BudgetOut(BaseModel):
    key: str
    limit_usd: float
    committed_usd: float


class AssistantStatus(BaseModel):
    generated_at: datetime
    model: str
    model_configured: bool
    read_only: Literal[True] = True
    providers: dict[str, bool]
    tools: list[str]
    limits: dict[str, float | int]
    budget: BudgetOut | None


async def _budget_status(settings: Settings) -> BudgetOut | None:
    from sg_core.db import get_sessionmaker

    now = datetime.now(UTC)
    key = budget_key_for(CostCenter.OWNER_ASSISTANT, at=now)
    try:
        async with get_sessionmaker()() as session:
            committed = await committed_usd(session, key, now)
    except Exception as exc:  # the page still renders without the figure
        log.warning("assistant.budget_status_failed", error=type(exc).__name__)
        return None
    limit: Decimal = monthly_limit_usd(CostCenter.OWNER_ASSISTANT, settings)
    return BudgetOut(key=key, limit_usd=float(limit), committed_usd=float(committed))


@router.get("/status", response_model=AssistantStatus)
async def assistant_status(_: OwnerDep, settings: SettingsDep) -> AssistantStatus:
    limits = limits_from_settings(settings)
    return AssistantStatus(
        generated_at=datetime.now(UTC),
        model=settings.owner_assistant_model or settings.llm_default_model,
        model_configured=settings.openrouter_api_key is not None,
        providers={
            "elevenlabs": bool(settings.elevenlabs_mcp_url),
            "tiger": bool(settings.tiger_mcp_url),
        },
        tools=sorted([ANALYTICS_QUERY, *(f"elevenlabs_{t}" for t in ELEVENLABS_READ_ONLY_TOOLS)]),
        limits={
            "max_rows": limits.max_rows,
            "max_tool_bytes": limits.max_tool_bytes,
            "max_tool_calls": limits.max_tool_calls,
            "max_steps": limits.max_steps,
            "tool_timeout_seconds": limits.tool_timeout_seconds,
            "max_concurrent_queries": limits.max_concurrent_queries,
        },
        budget=await _budget_status(settings),
    )
