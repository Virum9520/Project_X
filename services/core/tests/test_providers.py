import json
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from sg_core.economics import InMemoryUsageRecorder, UsageContext
from sg_core.models.enums import CostCenter
from sg_core.providers import (
    ChatMessage,
    ElevenLabsClient,
    EmbeddingClient,
    InMemoryObjectStore,
    LLMClient,
    ObjectNotFoundError,
    ProviderError,
    SandboxClient,
    SandboxFile,
)
from sg_core.providers.base import request_with_retry
from sg_core.providers.llm import _parse_response

CTX = UsageContext(cost_center=CostCenter.LEARNER, component="test", idempotency_key="k1")
KEY = SecretStr("secret")


def _transport(handler: httpx.MockTransport | object) -> httpx.MockTransport:
    return handler if isinstance(handler, httpx.MockTransport) else httpx.MockTransport(handler)  # type: ignore[arg-type]


# ── OpenRouter ──
async def test_llm_records_provider_reported_cost_and_sends_fallbacks() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "id": "gen-1",
                "model": "openai/gpt-4o-mini",
                "choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "cost": 0.00042,
                    "prompt_tokens_details": {"cached_tokens": 40},
                    "completion_tokens_details": {"reasoning_tokens": 5},
                },
            },
        )

    rec = InMemoryUsageRecorder()
    client = LLMClient(
        KEY, fallback_models=["openai/gpt-4o-mini"], transport=_transport(handler), recorder=rec
    )
    out = await client.complete([ChatMessage(role="user", content="hi")], usage=CTX)
    assert out.json_content() == {"a": 1}
    assert seen["models"] == ["anthropic/claude-sonnet-4.5", "openai/gpt-4o-mini"]
    assert seen["usage"] == {"include": True}
    assert seen["auth"] == "Bearer secret"
    _, measure = rec.records[0]
    assert measure.model == "openai/gpt-4o-mini"  # the model that actually served it
    assert measure.reported_cost_usd == Decimal("0.00042")
    assert (measure.input_tokens, measure.cache_read_tokens, measure.reasoning_tokens) == (
        100,
        40,
        5,
    )


async def test_llm_without_usage_context_records_nothing() -> None:
    rec = InMemoryUsageRecorder()
    body = {"choices": [{"message": {"content": "x"}}], "model": "m"}
    client = LLMClient(
        KEY, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)), recorder=rec
    )
    await client.complete([ChatMessage(role="user", content="hi")])
    assert rec.records == []


def test_llm_parse_tool_calls_and_missing_cost() -> None:
    data = {
        "model": "m",
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "f", "arguments": '{"x": 2}'}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    out = _parse_response(data, requested_model="m")
    assert out.tool_calls[0].parsed_arguments() == {"x": 2}
    assert out.usage.cost_usd is None


def test_llm_error_payload_raises() -> None:
    with pytest.raises(ProviderError):
        _parse_response({"error": {"message": "boom"}}, requested_model="m")


async def test_retry_on_429_then_success_and_no_retry_on_400() -> None:
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return (
            httpx.Response(429, headers={"retry-after": "0"})
            if calls["n"] == 1
            else httpx.Response(200, json={})
        )

    async def no_sleep(_: float) -> None:
        return None

    async with httpx.AsyncClient(transport=httpx.MockTransport(flaky), base_url="http://x") as http:
        await request_with_retry(http, "p", "GET", "/", sleep=no_sleep)
    assert calls["n"] == 2

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(400, text="bad")),
        base_url="http://x",
    ) as http:
        with pytest.raises(ProviderError) as exc:
            await request_with_retry(http, "p", "GET", "/", sleep=no_sleep)
    assert exc.value.status_code == 400
    assert not exc.value.retryable


# ── OpenAI embeddings ──
async def test_embeddings_batches_orders_and_records_tokens() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["dimensions"] == 4
        data = [
            {"index": i, "embedding": [float(i)] * 4} for i in reversed(range(len(body["input"])))
        ]
        return httpx.Response(
            200, json={"data": data, "model": body["model"], "usage": {"prompt_tokens": 7}}
        )

    rec = InMemoryUsageRecorder()
    client = EmbeddingClient(
        KEY, dimensions=4, transport=httpx.MockTransport(handler), recorder=rec
    )
    vectors = await client.embed(["a", "b", "c"], usage=CTX)
    assert [v[0] for v in vectors] == [0.0, 1.0, 2.0]
    assert rec.records[0][1].input_tokens == 7
    with pytest.raises(ValueError):
        await client.embed(["ok", "  "])


async def test_embeddings_rejects_wrong_dimension() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]})

    client = EmbeddingClient(KEY, dimensions=4, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        await client.embed(["a"])


# ── ElevenLabs ──
async def test_elevenlabs_tts_records_characters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/text-to-speech/voice1"
        return httpx.Response(
            200, content=b"mp3", headers={"content-type": "audio/mpeg", "character-cost": "5"}
        )

    rec = InMemoryUsageRecorder()
    client = ElevenLabsClient(KEY, transport=httpx.MockTransport(handler), recorder=rec)
    audio = await client.text_to_speech("voice1", "hello", usage=CTX)
    assert audio.audio == b"mp3"
    measure = rec.records[0][1]
    assert (measure.billable_unit, measure.billable_units) == ("tts_character", Decimal(5))


async def test_elevenlabs_conversation_usage_is_idempotent_keyed_by_conversation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "conversation_id": "c1",
                "agent_id": "a",
                "status": "done",
                "metadata": {"call_duration_secs": 61.5},
            },
        )

    rec = InMemoryUsageRecorder()
    client = ElevenLabsClient(KEY, transport=httpx.MockTransport(handler), recorder=rec)
    ctx = UsageContext(cost_center=CostCenter.LEARNER, component="drona_session")
    await client.record_conversation_usage("c1", ctx)
    context, measure = rec.records[0]
    assert context.idempotency_key == "elevenlabs:conversation:c1"
    assert measure.connected_seconds == Decimal("61.5")


async def test_elevenlabs_unmetered_without_usage_context() -> None:
    rec = InMemoryUsageRecorder()
    client = ElevenLabsClient(
        KEY,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x")),
        recorder=rec,
    )
    await client.compose_music("calm", length_ms=1000)
    assert rec.records == []


# ── E2B (fake backend) ──
class FakeBackend:
    def __init__(
        self, *, result: tuple[int, str, str] = (0, "ok", ""), raises: Exception | None = None
    ) -> None:
        self.result, self.raises = result, raises
        self.killed = 0
        self.written: list[str] = []
        self.created_with: dict[str, object] = {}

    async def create(self, *, template: str, timeout_seconds: int, allow_internet: bool) -> object:
        self.created_with = {"internet": allow_internet, "timeout": timeout_seconds}
        return object()

    async def write_file(self, sandbox: object, path: str, content: str | bytes) -> None:
        self.written.append(path)

    async def run(
        self, sandbox: object, command: str, *, timeout_seconds: float, env: dict[str, str]
    ) -> tuple[int, str, str]:
        if self.raises:
            raise self.raises
        return self.result

    async def kill(self, sandbox: object) -> None:
        self.killed += 1

    def sandbox_id(self, sandbox: object) -> str | None:
        return "sbx-1"


async def test_sandbox_runs_offline_kills_and_records() -> None:
    backend, rec = FakeBackend(result=(1, "out", "err")), InMemoryUsageRecorder()
    client = SandboxClient(backend, recorder=rec)
    result = await client.run("pytest", files=[SandboxFile("t.py", "x")], usage=CTX)
    assert (result.exit_code, result.ok, backend.killed) == (1, False, 1)
    assert backend.created_with["internet"] is False
    assert backend.written == ["t.py"]
    assert rec.records[0][1].sandbox_seconds is not None
    assert rec.records[0][1].external_ref == "sbx-1"


async def test_sandbox_timeout_is_a_result_and_still_kills() -> None:
    backend = FakeBackend(raises=TimeoutError())
    result = await SandboxClient(backend).run("sleep 99", timeout_seconds=1)
    assert result.timed_out and result.exit_code == 124 and backend.killed == 1


async def test_sandbox_unexpected_error_propagates_after_kill() -> None:
    backend = FakeBackend(raises=RuntimeError("platform down"))
    with pytest.raises(RuntimeError):
        await SandboxClient(backend).run("x")
    assert backend.killed == 1


# ── Object store ──
async def test_in_memory_store_contract_and_usage() -> None:
    rec = InMemoryUsageRecorder()
    store = InMemoryObjectStore(recorder=rec)
    await store.put("a/b.txt", b"hello", content_type="text/plain", usage=CTX)
    assert (await store.get("a/b.txt")).data == b"hello"
    assert await store.list_keys("a/") == ["a/b.txt"]
    assert rec.records[0][1].storage_bytes == 5
    await store.delete("a/b.txt")
    assert not await store.exists("a/b.txt")
    with pytest.raises(ObjectNotFoundError):
        await store.get("a/b.txt")


async def test_s3_store_maps_missing_key_and_presigns_locally() -> None:
    from sg_core.providers import S3ObjectStore

    store = S3ObjectStore(
        bucket="b", endpoint_url="http://localhost:9000", access_key_id="k", secret_access_key="s"
    )
    url = await store.presigned_get_url("x/y.png", expires_seconds=60)
    assert url.startswith("http://localhost:9000/b/x/y.png?") and "X-Amz-Signature" in url
