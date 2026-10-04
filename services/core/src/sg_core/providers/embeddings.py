"""OpenAI embeddings client (`EmbeddingClient`), sized to the schema's `vector(1536)` columns."""

from collections.abc import Sequence
from types import TracebackType
from typing import Self

import httpx
from pydantic import SecretStr

from sg_core.economics.usage import NullUsageRecorder, UsageContext, UsageMeasure, UsageRecorder
from sg_core.models.base import EMBEDDING_DIM
from sg_core.providers.base import ProviderError, ProviderNotConfiguredError, request_with_retry

PROVIDER = "openai"
MAX_BATCH = 256  # OpenAI allows 2048 inputs; stay well inside request-size limits


class EmbeddingClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str = "https://api.openai.com/v1",
        model: str = "text-embedding-3-small",
        dimensions: int = EMBEDDING_DIM,
        timeout: float = 60.0,
        retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        recorder: UsageRecorder | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key.get_secret_value()}"},
            timeout=timeout,
            transport=transport,
        )
        self._model = model
        self._dimensions = dimensions
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

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(
        self, texts: Sequence[str], *, usage: UsageContext | None = None
    ) -> list[list[float]]:
        """Embed texts, preserving order. Batches transparently; empty strings are rejected."""
        if any(not t.strip() for t in texts):
            raise ValueError("cannot embed empty text")
        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_BATCH):
            batch = list(texts[start : start + MAX_BATCH])
            # One idempotency key per batch so a retried multi-batch call records each once.
            batch_usage = _batch_context(usage, start // MAX_BATCH, len(texts) > MAX_BATCH)
            vectors.extend(await self._embed_batch(batch, batch_usage))
        return vectors

    async def embed_one(self, text: str, *, usage: UsageContext | None = None) -> list[float]:
        return (await self.embed([text], usage=usage))[0]

    async def _embed_batch(self, batch: list[str], usage: UsageContext | None) -> list[list[float]]:
        response = await request_with_retry(
            self._http,
            PROVIDER,
            "POST",
            "/embeddings",
            json={"model": self._model, "input": batch, "dimensions": self._dimensions},
            retries=self._retries,
        )
        data = response.json()
        items = sorted(data.get("data") or [], key=lambda d: d["index"])
        if len(items) != len(batch):
            raise ProviderError(
                PROVIDER, None, f"expected {len(batch)} embeddings, got {len(items)}"
            )
        vectors = [item["embedding"] for item in items]
        if any(len(v) != self._dimensions for v in vectors):
            raise ProviderError(PROVIDER, None, f"embedding size is not {self._dimensions}")
        if usage is not None:
            tokens = (data.get("usage") or {}).get("prompt_tokens")
            await self._recorder.record(
                usage,
                UsageMeasure(
                    provider=PROVIDER,
                    model=data.get("model") or self._model,
                    input_tokens=tokens,
                ),
            )
        return vectors


def _batch_context(usage: UsageContext | None, index: int, multi: bool) -> UsageContext | None:
    if usage is None or not multi or usage.idempotency_key is None:
        return usage
    return UsageContext(
        cost_center=usage.cost_center,
        component=usage.component,
        user_id=usage.user_id,
        session_id=usage.session_id,
        idempotency_key=f"{usage.idempotency_key}:batch{index}",
        environment=usage.environment,
    )


def embedding_client_from_settings(recorder: UsageRecorder | None = None) -> EmbeddingClient:
    from sg_core.economics.ledger import DbUsageRecorder
    from sg_core.settings import get_settings

    s = get_settings()
    if s.openai_api_key is None:
        raise ProviderNotConfiguredError("OPENAI_API_KEY is not configured")
    return EmbeddingClient(
        s.openai_api_key,
        base_url=s.openai_base_url,
        model=s.embedding_model,
        recorder=recorder or DbUsageRecorder(),
    )
