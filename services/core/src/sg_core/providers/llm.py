"""OpenRouter chat-completions client (`LLMClient`).

One adapter for every text model: judge, memory extraction, Sanjaya, owner assistant. Callers pick
a model slug; routing fallbacks come from `Settings.llm_fallback_models`. OpenRouter reports the
real cost with `usage: {include: true}`, so the ledger records it as provider cost.
"""

import json
from decimal import Decimal
from types import TracebackType
from typing import Any, Literal, Self

import httpx
from pydantic import BaseModel, SecretStr

from sg_core.economics.usage import NullUsageRecorder, UsageContext, UsageMeasure, UsageRecorder
from sg_core.providers.base import ProviderError, ProviderNotConfiguredError, request_with_retry

PROVIDER = "openrouter"


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    def wire(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # raw JSON string as sent by the model; validate before use

    def parsed_arguments(self) -> dict[str, Any]:
        value = json.loads(self.arguments or "{}")
        if not isinstance(value, dict):
            raise ValueError("tool arguments must be a JSON object")
        return value


class LLMUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: Decimal | None = None


class LLMResponse(BaseModel):
    id: str | None = None
    model: str
    content: str | None = None
    tool_calls: list[ToolCall] = []
    finish_reason: str | None = None
    usage: LLMUsage = LLMUsage()

    def json_content(self) -> Any:
        """Parse `content` as JSON (for `response_format` calls). Raises ValueError if absent."""
        if not self.content:
            raise ValueError("model returned no content")
        return json.loads(self.content)


class LLMClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        default_model: str = "anthropic/claude-sonnet-4.5",
        fallback_models: list[str] | None = None,
        timeout: float = 120.0,
        retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        recorder: UsageRecorder | None = None,
        app_title: str = "Skill Garden",
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key.get_secret_value()}",
                "X-Title": app_title,
            },
            timeout=timeout,
            transport=transport,
        )
        self._default_model = default_model
        self._fallbacks = fallback_models or []
        self._retries = retries
        self._recorder: UsageRecorder = recorder or NullUsageRecorder()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        usage: UsageContext | None = None,
    ) -> LLMResponse:
        """One non-streaming completion. `response_format={"type": "json_object"}` for JSON."""
        primary = model or self._default_model
        body: dict[str, Any] = {
            "model": primary,
            "messages": [m.wire() for m in messages],
            "usage": {"include": True},
        }
        # OpenRouter tries `models` in order when the primary fails or is unavailable.
        fallbacks = [m for m in self._fallbacks if m != primary]
        if fallbacks:
            body["models"] = [primary, *fallbacks]
        for key, value in {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools,
            "tool_choice": tool_choice,
            "response_format": response_format,
        }.items():
            if value is not None:
                body[key] = value

        response = await request_with_retry(
            self._http, PROVIDER, "POST", "/chat/completions", json=body, retries=self._retries
        )
        result = _parse_response(response.json(), requested_model=primary)
        if usage is not None:
            await self._recorder.record(
                usage,
                UsageMeasure(
                    provider=PROVIDER,
                    model=result.model,
                    external_ref=result.id,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    cache_read_tokens=result.usage.cache_read_tokens,
                    cache_write_tokens=result.usage.cache_write_tokens,
                    reasoning_tokens=result.usage.reasoning_tokens,
                    reported_cost_usd=result.usage.cost_usd,
                ),
            )
        return result


def _parse_response(data: dict[str, Any], *, requested_model: str) -> LLMResponse:
    if data.get("error"):
        raise ProviderError(PROVIDER, None, str(data["error"])[:500])
    choices = data.get("choices") or []
    if not choices:
        raise ProviderError(PROVIDER, None, "response had no choices")
    choice = choices[0]
    message = choice.get("message") or {}
    raw_usage = data.get("usage") or {}
    prompt_details = raw_usage.get("prompt_tokens_details") or {}
    completion_details = raw_usage.get("completion_tokens_details") or {}
    cost = raw_usage.get("cost")
    return LLMResponse(
        id=data.get("id"),
        # `model` is what actually served the request (may be a fallback).
        model=data.get("model") or requested_model,
        content=message.get("content"),
        tool_calls=[
            ToolCall(
                id=tc.get("id", ""),
                name=(tc.get("function") or {}).get("name", ""),
                arguments=(tc.get("function") or {}).get("arguments", ""),
            )
            for tc in message.get("tool_calls") or []
        ],
        finish_reason=choice.get("finish_reason"),
        usage=LLMUsage(
            input_tokens=raw_usage.get("prompt_tokens"),
            output_tokens=raw_usage.get("completion_tokens"),
            cache_read_tokens=prompt_details.get("cached_tokens"),
            cache_write_tokens=prompt_details.get("cache_write_tokens"),
            reasoning_tokens=completion_details.get("reasoning_tokens"),
            cost_usd=None if cost is None else Decimal(str(cost)),
        ),
    )


def llm_client_from_settings(recorder: UsageRecorder | None = None) -> LLMClient:
    from sg_core.economics.ledger import DbUsageRecorder
    from sg_core.settings import get_settings

    s = get_settings()
    if s.openrouter_api_key is None:
        raise ProviderNotConfiguredError("OPENROUTER_API_KEY is not configured")
    return LLMClient(
        s.openrouter_api_key,
        base_url=s.openrouter_base_url,
        default_model=s.llm_default_model,
        fallback_models=s.llm_fallback_models,
        recorder=recorder or DbUsageRecorder(),
    )
