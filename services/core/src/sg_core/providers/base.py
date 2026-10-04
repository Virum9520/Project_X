"""Shared plumbing for provider adapters: errors, retrying HTTP, usage hand-off."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class ProviderError(RuntimeError):
    """A provider call failed. `status_code` is None for transport failures."""

    def __init__(self, provider: str, status_code: int | None, detail: str) -> None:
        super().__init__(f"{provider} error {status_code or 'transport'}: {detail}")
        self.provider = provider
        self.status_code = status_code
        self.detail = detail

    @property
    def retryable(self) -> bool:
        return self.status_code is None or self.status_code in RETRYABLE_STATUS


class ProviderNotConfiguredError(RuntimeError):
    """The API key (or other setting) for a provider is missing."""


async def request_with_retry(
    http: httpx.AsyncClient,
    provider: str,
    method: str,
    path: str,
    *,
    retries: int = 2,
    backoff: float = 0.5,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    **kwargs: Any,
) -> httpx.Response:
    """Send a request, retrying 429/5xx and transport errors with jittered exponential backoff.

    Honors `Retry-After` (seconds). Raises `ProviderError` for the final failure.
    """
    attempt = 0
    while True:
        try:
            response = await http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            if attempt >= retries:
                raise ProviderError(provider, None, f"{type(exc).__name__}: {exc}") from exc
            delay = backoff * 2**attempt
        else:
            if response.status_code < 400:
                return response
            if response.status_code not in RETRYABLE_STATUS or attempt >= retries:
                raise ProviderError(provider, response.status_code, response.text[:500])
            retry_after = response.headers.get("retry-after", "")
            delay = float(retry_after) if retry_after.isdigit() else backoff * 2**attempt
        await sleep(delay + random.uniform(0, backoff / 4))
        attempt += 1
