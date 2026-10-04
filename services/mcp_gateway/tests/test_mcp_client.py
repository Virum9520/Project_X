import json

import httpx
import pytest
from pydantic import SecretStr

from sg_mcp_gateway.mcp_client import HttpMcpClient, McpProtocolError, McpUnavailableError


def make(handler, token: str | None = "secret-token") -> HttpMcpClient:  # type: ignore[no-untyped-def]
    return HttpMcpClient(
        "https://mcp.example.test/mcp",
        SecretStr(token) if token else None,
        transport=httpx.MockTransport(handler),
    )


def server(requests: list[httpx.Request]):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        method = body["method"]
        if method == "initialize":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": {"capabilities": {}}},
                headers={"Mcp-Session-Id": "sess-1"},
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            page2 = body["params"].get("cursor") == "p2"
            result = (
                {"tools": [{"name": "b", "inputSchema": {}}]}
                if page2
                else {
                    "tools": [
                        {
                            "name": "a",
                            "description": "d",
                            "inputSchema": {"type": "object"},
                            "annotations": {"readOnlyHint": True},
                        }
                    ],
                    "nextCursor": "p2",
                }
            )
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})
        if method == "tools/call":
            reply = {
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"content": [{"type": "text", "text": "hi"}], "isError": False},
            }
            sse = "event: message\ndata: " + json.dumps(reply) + "\n\n"
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
        return httpx.Response(404)

    return handler


async def test_initialize_list_and_call_over_json_and_sse() -> None:
    seen: list[httpx.Request] = []
    client = make(server(seen))
    tools = await client.list_tools()
    assert [t.name for t in tools] == ["a", "b"]
    assert tools[0].annotations == {"readOnlyHint": True}
    result = await client.call_tool("a", {"x": 1})
    assert result.text == "hi" and not result.is_error
    # initialize once, then session header is reused and the bearer token is sent
    assert [json.loads(r.content).get("method") for r in seen][:2] == [
        "initialize",
        "notifications/initialized",
    ]
    assert all(r.headers["authorization"] == "Bearer secret-token" for r in seen)
    assert seen[-1].headers["mcp-session-id"] == "sess-1"
    await client.aclose()


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
async def test_auth_and_server_failures_mean_unavailable(status: int) -> None:
    client = make(lambda request: httpx.Response(status))
    with pytest.raises(McpUnavailableError):
        await client.list_tools()


async def test_transport_error_means_unavailable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    with pytest.raises(McpUnavailableError):
        await make(boom).list_tools()


async def test_jsonrpc_error_is_protocol_error_and_hides_nothing_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
        if "id" not in body:
            return httpx.Response(202)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "error": {"message": "bad tool"}}
        )

    with pytest.raises(McpProtocolError, match="bad tool"):
        await make(handler).call_tool("x", {})


async def test_invalid_json_is_protocol_error() -> None:
    client = make(lambda request: httpx.Response(200, text="<html>"))
    with pytest.raises(McpProtocolError):
        await client.list_tools()
