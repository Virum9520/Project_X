"""The tool gateway: authenticated callers only, an explicit read-only allowlist, hard limits,
and an audit record for every call (including refused ones).

Two upstreams:
- ElevenLabs hosted MCP: only allowlisted, non-destructive agent and conversation inspection tools.
- Tiger MCP: only `db_execute_query`, only validated SELECTs over `analytics.*`, row-capped.

A provider that is not configured or not reachable never raises into the caller: the outcome is
marked `unavailable` so the answer can be explicitly partial.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from sg_core.identity import AuditEvent, AuditSink
from sg_core.logging import get_logger
from sg_mcp_gateway.mcp_client import McpClient, McpProtocolError, McpTool, McpUnavailableError
from sg_mcp_gateway.policy import (
    GatewayLimits,
    PolicyError,
    limit_rows,
    truncate_json,
    validate_readonly_sql,
    wrap_untrusted,
)

log = get_logger(__name__)

ELEVENLABS = "elevenlabs"
TIGER = "tiger"
ANALYTICS_QUERY = "analytics_query"
TIGER_QUERY_UPSTREAM = "db_execute_query"

# Read-only inspection tools of the ElevenLabs hosted MCP that the assistant may use. Anything
# else the server offers (creating agents, placing calls, editing voices) is never exposed. The
# exact tool inventory must be confirmed against the live server (see docs/PROGRESS.md, C22).
ELEVENLABS_READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "list_agents",
        "get_agent",
        "list_conversations",
        "get_conversation",
        "get_agent_llm_expected_cost",
        "calculate_agent_llm_expected_cost",
    }
)
MAX_ARGUMENT_CHARS = 4000
TOOLS_TTL_SECONDS = 60.0

ANALYTICS_QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sql": {
            "type": "string",
            "description": (
                "One PostgreSQL SELECT over analytics.<view> relations. Read-only, no comments."
            ),
        }
    },
    "required": ["sql"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class CallContext:
    """Who is asking; copied into every audit record."""

    actor_id: str
    actor_email: str | None
    request_id: str
    ip: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class ToolDef:
    name: str  # what the model sees
    provider: str
    upstream: str
    description: str
    parameters: dict[str, Any]

    def openai_spec(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(slots=True)
class ToolOutcome:
    tool: str
    provider: str | None
    ok: bool
    content: str  # the untrusted-data envelope handed back to the model
    unavailable: bool = False
    refused: bool = False
    rows: int | None = None
    truncated: bool = False
    bytes_returned: int = 0
    duration_ms: int = 0
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class McpGateway:
    def __init__(
        self,
        *,
        audit: AuditSink,
        limits: GatewayLimits | None = None,
        elevenlabs: McpClient | None = None,
        tiger: McpClient | None = None,
        tiger_service_id: str | None = None,
        elevenlabs_allowed: frozenset[str] = ELEVENLABS_READ_ONLY_TOOLS,
    ) -> None:
        self.limits = limits or GatewayLimits()
        self._audit = audit
        self._clients: dict[str, McpClient | None] = {ELEVENLABS: elevenlabs, TIGER: tiger}
        self._tiger_service_id = tiger_service_id
        self._allowed_el = elevenlabs_allowed
        self._query_slots = asyncio.Semaphore(self.limits.max_concurrent_queries)
        self._cache: dict[str, tuple[float, list[McpTool]]] = {}

    # ── discovery ──
    def configured(self) -> dict[str, bool]:
        return {name: client is not None for name, client in self._clients.items()}

    async def _upstream_tools(self, provider: str) -> list[McpTool]:
        client = self._clients[provider]
        if client is None:
            raise McpUnavailableError(f"{provider} MCP is not configured")
        cached = self._cache.get(provider)
        if cached and time.monotonic() - cached[0] < TOOLS_TTL_SECONDS:
            return cached[1]
        tools = await asyncio.wait_for(client.list_tools(), self.limits.tool_timeout_seconds)
        self._cache[provider] = (time.monotonic(), tools)
        return tools

    async def tools(self) -> tuple[list[ToolDef], dict[str, str]]:
        """Tools the model may call now, plus `{provider: reason}` for each unavailable one."""
        defs: list[ToolDef] = []
        unavailable: dict[str, str] = {}
        for provider in (TIGER, ELEVENLABS):
            try:
                upstream = await self._upstream_tools(provider)
            except (McpUnavailableError, McpProtocolError, TimeoutError) as exc:
                unavailable[provider] = _reason(exc)
                continue
            names = {t.name: t for t in upstream}
            if provider == TIGER:
                if TIGER_QUERY_UPSTREAM in names:
                    defs.append(_analytics_tool())
                else:
                    unavailable[provider] = "query tool not offered by the server"
                continue
            for tool in upstream:
                if tool.name in self._allowed_el and _is_read_only(tool):
                    defs.append(
                        ToolDef(
                            name=f"{ELEVENLABS}_{tool.name}",
                            provider=ELEVENLABS,
                            upstream=tool.name,
                            description=(tool.description or tool.name)[:500],
                            parameters=tool.input_schema or {"type": "object", "properties": {}},
                        )
                    )
        return defs, unavailable

    # ── execution ──
    async def call(
        self, ctx: CallContext, name: str, arguments: dict[str, Any], defs: list[ToolDef]
    ) -> ToolOutcome:
        started = time.monotonic()
        tool = next((d for d in defs if d.name == name), None)
        if tool is None:
            outcome = _refusal(name, None, "that tool is not available to the assistant")
        else:
            try:
                outcome = await self._run(tool, arguments)
            except PolicyError as exc:
                outcome = _refusal(name, tool.provider, str(exc))
        outcome.duration_ms = int((time.monotonic() - started) * 1000)
        await self._record(ctx, name, arguments, outcome)
        return outcome

    async def refuse(self, ctx: CallContext, name: str, why: str) -> ToolOutcome:
        """Record a refused call (for example unparseable arguments) and return the outcome."""
        outcome = _refusal(name, None, why)
        await self._record(ctx, name, {}, outcome)
        return outcome

    async def _run(self, tool: ToolDef, arguments: dict[str, Any]) -> ToolOutcome:
        if len(json.dumps(arguments, default=str)) > MAX_ARGUMENT_CHARS:
            raise PolicyError("tool arguments are too large")
        client = self._clients[tool.provider]
        if client is None:
            return _unavailable(tool, "not configured")
        upstream_args: dict[str, Any]
        if tool.name == ANALYTICS_QUERY:
            sql = arguments.get("sql")
            if not isinstance(sql, str) or set(arguments) - {"sql"}:
                raise PolicyError("analytics_query takes exactly one argument, sql")
            safe = validate_readonly_sql(sql)
            upstream_args = {"query": limit_rows(safe, self.limits.max_rows)}
            if self._tiger_service_id:
                upstream_args["service_id"] = self._tiger_service_id
            if "timeout_seconds" in await self._tiger_schema_properties():
                upstream_args["timeout_seconds"] = int(self.limits.tool_timeout_seconds)
        else:
            upstream_args = arguments
        try:
            async with self._slot(tool.provider):
                result = await asyncio.wait_for(
                    client.call_tool(tool.upstream, upstream_args),
                    self.limits.tool_timeout_seconds,
                )
        except (McpUnavailableError, TimeoutError) as exc:
            return _unavailable(tool, _reason(exc))
        except McpProtocolError as exc:
            return _failed(tool, str(exc))
        if result.is_error:
            return _failed(tool, result.text[:300] or "the tool reported an error")
        return self._shape(tool, result.text, result.structured)

    def _slot(self, provider: str) -> "_Slot":
        return _Slot(self._query_slots if provider == TIGER else None)

    async def _tiger_schema_properties(self) -> dict[str, Any]:
        try:
            for tool in await self._upstream_tools(TIGER):
                if tool.name == TIGER_QUERY_UPSTREAM:
                    props = tool.input_schema.get("properties")
                    return props if isinstance(props, dict) else {}
        except (McpUnavailableError, McpProtocolError, TimeoutError):
            pass
        return {}

    def _shape(self, tool: ToolDef, text: str, structured: Any) -> ToolOutcome:
        data: Any = structured
        if data is None:
            try:
                data = json.loads(text)
            except ValueError:
                data = text
        rows: int | None = None
        truncated = False
        if tool.name == ANALYTICS_QUERY:
            seq = data.get("rows") if isinstance(data, dict) else data
            if isinstance(seq, list):
                truncated = len(seq) > self.limits.max_rows
                seq = seq[: self.limits.max_rows]
                rows = len(seq)
                data = {"rows": seq}
        body, cut = truncate_json(data, self.limits.max_tool_bytes)
        truncated = truncated or cut
        payload: dict[str, Any] = {"truncated": truncated}
        if rows is not None:
            payload["row_count"] = rows
        payload["result"] = body if cut else data
        content = wrap_untrusted(tool.provider, tool.name, payload)
        return ToolOutcome(
            tool=tool.name,
            provider=tool.provider,
            ok=True,
            content=content,
            rows=rows,
            truncated=truncated,
            bytes_returned=len(content.encode("utf-8")),
        )

    async def _record(
        self, ctx: CallContext, name: str, arguments: dict[str, Any], outcome: ToolOutcome
    ) -> None:
        if outcome.refused:
            action, status = "assistant.tool_refused", 403
        elif outcome.unavailable:
            action, status = "assistant.tool_call", 503
        else:
            action, status = "assistant.tool_call", 200 if outcome.ok else 502
        args_text = json.dumps(arguments, default=str, ensure_ascii=False)[:1000]
        event = AuditEvent(
            actor_id=ctx.actor_id,
            actor_email=ctx.actor_email,
            action=action,
            request_id=ctx.request_id,
            status_code=status,
            target=f"{outcome.provider or 'gateway'}:{name}"[:200],
            after={
                "arguments": args_text,
                "ok": outcome.ok,
                "rows": outcome.rows,
                "truncated": outcome.truncated,
                "bytes": outcome.bytes_returned,
                "duration_ms": outcome.duration_ms,
                "error": outcome.error,
            },
            ip=ctx.ip,
            user_agent=ctx.user_agent,
        )
        try:
            await self._audit.record(event)
        except Exception as exc:  # loud, but a sink failure must not change the answer
            log.error("assistant.audit_failed", error=str(exc), action=action)

    async def aclose(self) -> None:
        for client in self._clients.values():
            if client is not None:
                await client.aclose()


class _Slot:
    def __init__(self, sem: asyncio.Semaphore | None) -> None:
        self._sem = sem

    async def __aenter__(self) -> None:
        if self._sem is not None:
            await self._sem.acquire()

    async def __aexit__(self, *_: object) -> None:
        if self._sem is not None:
            self._sem.release()


def _analytics_tool() -> ToolDef:
    return ToolDef(
        name=ANALYTICS_QUERY,
        provider=TIGER,
        upstream=TIGER_QUERY_UPSTREAM,
        description=(
            "Run one read-only SQL SELECT over the analytics views (see the catalogue in the "
            "system prompt). Results are capped in rows and size."
        ),
        parameters=ANALYTICS_QUERY_SCHEMA,
    )


def _is_read_only(tool: McpTool) -> bool:
    ann = tool.annotations
    return ann.get("destructiveHint") is not True and ann.get("readOnlyHint") is not False


def _reason(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timed out"
    return str(exc)[:200]


def _refusal(name: str, provider: str | None, why: str) -> ToolOutcome:
    content = wrap_untrusted(provider or "gateway", name, {"error": why, "refused": True})
    return ToolOutcome(
        tool=name, provider=provider, ok=False, refused=True, content=content, error=why
    )


def _unavailable(tool: ToolDef, why: str) -> ToolOutcome:
    msg = f"{tool.provider} is unavailable ({why}); answer only from other sources and say so"
    content = wrap_untrusted(tool.provider, tool.name, {"error": msg, "provider_unavailable": True})
    return ToolOutcome(
        tool=tool.name,
        provider=tool.provider,
        ok=False,
        unavailable=True,
        content=content,
        error=msg,
    )


def _failed(tool: ToolDef, why: str) -> ToolOutcome:
    content = wrap_untrusted(tool.provider, tool.name, {"error": why})
    return ToolOutcome(tool=tool.name, provider=tool.provider, ok=False, content=content, error=why)
