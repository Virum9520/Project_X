"""The owner assistant loop: an OpenRouter tool-use model over the gateway's tools.

Every model turn runs inside a budget hold (`owner_assistant:YYYY-MM`) and is recorded in the
usage ledger by the LLM adapter. Tool calls go through `McpGateway` (allowlist, limits, audit).
Tool output is wrapped as untrusted data before the model sees it.
"""

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from sg_core.economics import UsageContext
from sg_core.economics.budget import BudgetExceededError
from sg_core.models.enums import CostCenter
from sg_core.providers.base import ProviderError
from sg_core.providers.llm import ChatMessage, LLMResponse
from sg_mcp_gateway.budget import AssistantBudget
from sg_mcp_gateway.gateway import CallContext, McpGateway, ToolOutcome
from sg_mcp_gateway.policy import wrap_untrusted
from sg_mcp_gateway.prompt import SYSTEM_PROMPT

MAX_QUESTION_CHARS = 2000
MAX_HISTORY_TURNS = 6
MAX_HISTORY_CHARS = 4000


class ChatModel(Protocol):
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        usage: UsageContext | None = None,
        temperature: float | None = None,
    ) -> LLMResponse: ...


class Basis(BaseModel):
    date_range: str = ""
    metrics: list[str] = []
    filters: list[str] = []
    freshness: str = ""
    amounts: str = ""


class _FinalAnswer(BaseModel):
    answer: str
    basis: Basis = Basis()
    hypotheses: list[str] = []


@dataclass(frozen=True, slots=True)
class HistoryTurn:
    role: str  # "user" | "assistant"
    content: str


@dataclass(slots=True)
class ToolTrace:
    tool: str
    provider: str | None
    ok: bool
    rows: int | None = None
    truncated: bool = False
    duration_ms: int = 0
    error: str | None = None


@dataclass(slots=True)
class AssistantAnswer:
    answer: str
    basis: Basis | None
    hypotheses: list[str]
    partial: bool
    unavailable_providers: dict[str, str]
    tools: list[ToolTrace]
    warnings: list[str]
    cost_usd: Decimal
    steps: int
    model: str | None
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    stopped: str | None = None  # budget | limit | provider_error


class OwnerAssistant:
    def __init__(
        self,
        *,
        llm: ChatModel,
        gateway: McpGateway,
        budget: AssistantBudget,
        model: str | None,
        turn_hold_usd: Decimal,
    ) -> None:
        self._llm = llm
        self._gateway = gateway
        self._budget = budget
        self._model = model
        self._hold = turn_hold_usd

    async def ask(
        self, ctx: CallContext, question: str, history: list[HistoryTurn] | None = None
    ) -> AssistantAnswer:
        limits = self._gateway.limits
        defs, unavailable = await self._gateway.tools()
        specs = [d.openai_spec() for d in defs]
        configured = self._gateway.configured()
        messages = [ChatMessage(role="system", content=_system_message(unavailable))]
        for turn in (history or [])[-MAX_HISTORY_TURNS:]:
            if turn.role in ("user", "assistant"):
                role: Any = turn.role
                messages.append(ChatMessage(role=role, content=turn.content[:MAX_HISTORY_CHARS]))
        messages.append(ChatMessage(role="user", content=question[:MAX_QUESTION_CHARS]))

        traces: list[ToolTrace] = []
        warnings: list[str] = []
        cost = Decimal(0)
        used_calls = 0
        served_model: str | None = None
        stopped: str | None = None
        response: LLMResponse | None = None

        for step in range(1, limits.max_steps + 1):
            may_use_tools = bool(specs) and step < limits.max_steps
            may_use_tools = may_use_tools and used_calls < limits.max_tool_calls
            try:
                async with self._budget.hold(self._hold) as hold:
                    response = await self._llm.complete(
                        messages,
                        model=self._model,
                        max_tokens=limits.max_output_tokens,
                        tools=specs if may_use_tools else None,
                        temperature=0.1,
                        usage=UsageContext(
                            cost_center=CostCenter.OWNER_ASSISTANT,
                            component="owner_assistant",
                            idempotency_key=f"owner_assistant:{ctx.request_id}:{step}",
                        ),
                    )
                    if response.usage.cost_usd is not None:
                        hold.actual_usd = response.usage.cost_usd
                    else:
                        hold.actual_usd = hold.reserved_usd
                    cost += hold.actual_usd
            except BudgetExceededError:
                stopped = "budget"
                warnings.append("The monthly owner-assistant budget is used up.")
                break
            except ProviderError as exc:
                stopped = "provider_error"
                warnings.append(f"The model provider failed ({exc.status_code or 'transport'}).")
                break
            served_model = response.model
            if not response.tool_calls or not may_use_tools:
                break
            messages.append(
                ChatMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=[
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": tc.arguments},
                        }
                        for tc in response.tool_calls
                    ],
                )
            )
            for tc in response.tool_calls:
                used_calls += 1
                if used_calls > limits.max_tool_calls:
                    outcome = _over_limit(tc.name)
                else:
                    outcome = await self._run_tool(ctx, tc.name, tc.arguments, defs)
                traces.append(
                    ToolTrace(
                        tool=outcome.tool,
                        provider=outcome.provider,
                        ok=outcome.ok,
                        rows=outcome.rows,
                        truncated=outcome.truncated,
                        duration_ms=outcome.duration_ms,
                        error=outcome.error,
                    )
                )
                if outcome.unavailable and outcome.provider:
                    unavailable.setdefault(outcome.provider, outcome.error or "unavailable")
                messages.append(
                    ChatMessage(role="tool", tool_call_id=tc.id, content=outcome.content)
                )

        text = (response.content or "") if response is not None and stopped is None else ""
        if stopped is None and response is not None and not text.strip():
            stopped = "limit"
        answer, basis, hypotheses = _parse_final(text, warnings)
        if stopped in ("limit",) and not answer:
            answer = "I ran out of steps before I could finish. Ask a narrower question."
        if stopped in ("budget", "provider_error") and not answer:
            answer = "I could not answer this question."
        if any(t.truncated for t in traces):
            warnings.append("At least one result was truncated by the gateway limits.")
        return AssistantAnswer(
            answer=answer,
            basis=basis,
            hypotheses=hypotheses,
            # Unconfigured providers are listed but only a configured one that fails (or having no
            # data source at all) makes the answer partial.
            partial=stopped is not None
            or not specs
            or any(configured.get(p, False) for p in unavailable),
            unavailable_providers=unavailable,
            tools=traces,
            warnings=warnings,
            cost_usd=cost,
            steps=min(step, limits.max_steps),
            model=served_model,
            stopped=stopped,
        )

    async def _run_tool(
        self, ctx: CallContext, name: str, raw_arguments: str, defs: list[Any]
    ) -> ToolOutcome:
        try:
            value = json.loads(raw_arguments or "{}")
            if not isinstance(value, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError:
            return await self._gateway.refuse(ctx, name, "tool arguments were not a JSON object")
        return await self._gateway.call(ctx, name, value, defs)


def _system_message(unavailable: dict[str, str]) -> str:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    text = f"{SYSTEM_PROMPT}\n\nToday is {today} (UTC)."
    if unavailable:
        lines = ", ".join(f"{p} ({r})" for p, r in sorted(unavailable.items()))
        text += f"\nCurrently unavailable providers: {lines}. Mention this in your answer."
    return text


def _over_limit(name: str) -> ToolOutcome:
    why = "tool call limit reached for this question; answer with what you have"
    return ToolOutcome(
        tool=name,
        provider=None,
        ok=False,
        refused=True,
        content=wrap_untrusted("gateway", name, {"error": why, "refused": True}),
        error=why,
    )


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _parse_final(text: str, warnings: list[str]) -> tuple[str, Basis | None, list[str]]:
    stripped = _FENCE_RE.sub("", text.strip()).strip()
    if not stripped:
        return "", None, []
    try:
        final = _FinalAnswer.model_validate(json.loads(stripped))
    except (ValueError, ValidationError):
        warnings.append("The answer did not state its basis (date range, definitions, freshness).")
        return text.strip(), None, []
    if not final.basis.date_range or not final.basis.freshness or not final.basis.amounts:
        warnings.append("The answer's basis is incomplete.")
    return final.answer, final.basis, final.hypotheses


def new_request_id() -> str:
    return uuid.uuid4().hex
