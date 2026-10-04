"""Minimal MCP client over streamable HTTP (JSON-RPC 2.0): initialize, tools/list, tools/call.

Only what the gateway needs. The bearer credential lives here and never reaches the model or the
browser. Servers may answer with JSON or a single SSE message; both are handled.
"""

import itertools
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import SecretStr

PROTOCOL_VERSION = "2025-06-18"


class McpUnavailableError(RuntimeError):
    """The server could not be reached or refused our credentials (a disconnected provider)."""


class McpProtocolError(RuntimeError):
    """The server answered, but with an error or something that is not valid MCP."""


@dataclass(frozen=True, slots=True)
class McpTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    annotations: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class McpResult:
    text: str
    is_error: bool = False
    structured: Any = None


class McpClient(Protocol):
    async def list_tools(self) -> list[McpTool]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpResult: ...

    async def aclose(self) -> None: ...


class HttpMcpClient:
    def __init__(
        self,
        url: str,
        token: SecretStr | None = None,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"Accept": "application/json, text/event-stream"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token.get_secret_value()}"
        self._url = url
        self._http = httpx.AsyncClient(headers=headers, timeout=timeout, transport=transport)
        self._ids = itertools.count(1)
        self._session_id: str | None = None
        self._ready = False

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, payload: dict[str, Any], *, expect_reply: bool) -> Any:
        headers = {"Content-Type": "application/json", "MCP-Protocol-Version": PROTOCOL_VERSION}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            response = await self._http.post(self._url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise McpUnavailableError(f"{type(exc).__name__}: could not reach MCP server") from exc
        if response.status_code in (401, 403):
            raise McpUnavailableError(
                f"MCP server refused the credentials ({response.status_code})"
            )
        if response.status_code >= 500 or response.status_code == 429:
            raise McpUnavailableError(f"MCP server error {response.status_code}")
        if response.status_code >= 400:
            raise McpProtocolError(f"MCP request rejected ({response.status_code})")
        if sid := response.headers.get("mcp-session-id"):
            self._session_id = sid
        if not expect_reply:
            return None
        return _parse_reply(response, payload["id"])

    async def _ensure_ready(self) -> None:
        if self._ready:
            return
        await self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "skill-garden-mcp-gateway", "version": "0.1.0"},
            },
            ensure=False,
        )
        await self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False
        )
        self._ready = True

    async def _rpc(self, method: str, params: dict[str, Any], *, ensure: bool = True) -> Any:
        if ensure:
            await self._ensure_ready()
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        message = await self._post(payload, expect_reply=True)
        if "error" in message:
            err = message["error"] or {}
            raise McpProtocolError(f"{method}: {str(err.get('message', 'error'))[:300]}")
        return message.get("result") or {}

    async def list_tools(self) -> list[McpTool]:
        tools: list[McpTool] = []
        cursor: str | None = None
        for _ in range(10):  # pagination guard
            result = await self._rpc("tools/list", {"cursor": cursor} if cursor else {})
            for raw in result.get("tools") or []:
                tools.append(
                    McpTool(
                        name=str(raw.get("name", "")),
                        description=str(raw.get("description") or ""),
                        input_schema=raw.get("inputSchema") or {},
                        annotations=raw.get("annotations") or {},
                    )
                )
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpResult:
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        parts = [
            str(item.get("text", ""))
            for item in result.get("content") or []
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return McpResult(
            text="\n".join(parts),
            is_error=bool(result.get("isError")),
            structured=result.get("structuredContent"),
        )


def _parse_reply(response: httpx.Response, request_id: int) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    try:
        if "text/event-stream" in content_type:
            for line in response.text.splitlines():
                if not line.startswith("data:"):
                    continue
                message = json.loads(line[5:].strip())
                if isinstance(message, dict) and message.get("id") == request_id:
                    return message
            raise McpProtocolError("no reply in event stream")
        message = response.json()
    except ValueError as exc:
        raise McpProtocolError("MCP server returned invalid JSON") from exc
    if not isinstance(message, dict):
        raise McpProtocolError("MCP server returned an unexpected reply")
    return message
