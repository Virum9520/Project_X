"""Test doubles: a scripted MCP server, a recording audit sink, a fake budget and a fake model."""

import json
from collections.abc import Callable, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from sg_core.economics.budget import BudgetExceededError, Hold
from sg_core.identity import AuditEvent
from sg_core.providers.llm import ChatMessage, LLMResponse, LLMUsage, ToolCall
from sg_mcp_gateway.mcp_client import McpResult, McpTool, McpUnavailableError


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)

    def actions(self) -> list[str]:
        return [e.action for e in self.events]


class FakeMcp:
    def __init__(
        self,
        tools: list[McpTool],
        handler: Callable[[str, dict[str, Any]], McpResult] | None = None,
        *,
        down: bool = False,
    ) -> None:
        self._tools = tools
        self._handler = handler or (lambda name, args: McpResult(text="{}"))
        self.down = down
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    async def list_tools(self) -> list[McpTool]:
        if self.down:
            raise McpUnavailableError("connection refused")
        return self._tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpResult:
        if self.down:
            raise McpUnavailableError("connection refused")
        self.calls.append((name, arguments))
        return self._handler(name, arguments)

    async def aclose(self) -> None:
        self.closed = True


TIGER_TOOL = McpTool(
    "db_execute_query",
    "run sql",
    {"type": "object", "properties": {"query": {}, "service_id": {}, "timeout_seconds": {}}},
)
EL_TOOLS = [
    McpTool("list_agents", "list agents", {"type": "object", "properties": {}}),
    McpTool("get_conversation", "get one", {"type": "object", "properties": {"id": {}}}),
    McpTool("create_agent", "create", {"type": "object"}),
    McpTool("start_outbound_call", "dial", {"type": "object"}),
    McpTool(
        "get_agent",
        "tool that claims it writes",
        {"type": "object"},
        {"readOnlyHint": False},
    ),
]


class FakeBudget:
    def __init__(self, limit: Decimal = Decimal("10")) -> None:
        self.limit = limit
        self.committed = Decimal(0)
        self.holds: list[Decimal] = []
        self.settled: list[Decimal] = []
        self.released = 0

    @asynccontextmanager
    async def hold(self, amount_usd: Decimal):  # type: ignore[no-untyped-def]
        if self.committed + amount_usd > self.limit:
            raise BudgetExceededError(
                "owner_assistant:test", self.limit, self.committed, amount_usd
            )
        self.holds.append(amount_usd)
        self.committed += amount_usd
        h = Hold(reservation_id=__import__("uuid").uuid4(), reserved_usd=amount_usd)
        try:
            yield h
        except BaseException:
            self.committed -= amount_usd
            self.released += 1
            raise
        actual = h.actual_usd if h.actual_usd is not None else amount_usd
        self.committed += actual - amount_usd
        self.settled.append(actual)


def tool_call(name: str, args: dict[str, Any] | str, id_: str = "call_1") -> ToolCall:
    return ToolCall(
        id=id_, name=name, arguments=args if isinstance(args, str) else json.dumps(args)
    )


def llm_response(
    content: str | None = None,
    calls: list[ToolCall] | None = None,
    cost: str | None = "0.01",
) -> LLMResponse:
    return LLMResponse(
        id="gen-1",
        model="test/model",
        content=content,
        tool_calls=calls or [],
        usage=LLMUsage(cost_usd=None if cost is None else Decimal(cost)),
    )


class ScriptedLLM:
    """Returns queued responses and records what it was asked."""

    def __init__(self, responses: Sequence[LLMResponse | Exception]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    async def complete(self, messages: list[ChatMessage], **kwargs: Any) -> LLMResponse:
        self.requests.append({"messages": list(messages), **kwargs})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


GOOD_FINAL = json.dumps(
    {
        "answer": "Spend was $1.20.",
        "basis": {
            "date_range": "2026-10-01 to 2026-10-04 UTC",
            "metrics": ["sum(usd_total) from analytics.daily_cost"],
            "filters": ["is_test not applicable"],
            "freshness": "cost_entries at 2026-10-04T10:00Z",
            "amounts": "mixed",
        },
        "hypotheses": [],
    }
)
