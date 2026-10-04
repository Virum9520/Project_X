"""Wire the pipeline's embedder and mapper from settings.

- Embeddings: the real OpenAI client (metered through the usage ledger) when `OPENAI_API_KEY` is
  set. In `local`/`test` without a key a deterministic hash provider keeps everything runnable.
  Elsewhere a missing key raises `ProviderNotConfiguredError`: hash vectors must never reach a
  hosted database. Chunks record `embedding_model`, and search only compares like with like.
- Concept mapping: the LLM mapper when `OPENROUTER_API_KEY` is set, else the keyword mapper.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from sg_core.economics.usage import UsageContext
from sg_core.knowledge.mapping import ConceptMapper, KeywordConceptMapper, LLMConceptMapper
from sg_core.memory.embeddings import EmbeddingProvider, HashEmbeddingProvider
from sg_core.providers.base import ProviderNotConfiguredError
from sg_core.providers.embeddings import EmbeddingClient, embedding_client_from_settings
from sg_core.providers.llm import llm_client_from_settings
from sg_core.settings import Environment, get_settings


class OpenAIEmbeddingProvider:
    """`EmbeddingProvider` over `EmbeddingClient`, carrying the usage context for metering."""

    def __init__(
        self, client: EmbeddingClient, model: str, usage: UsageContext | None = None
    ) -> None:
        self._client = client
        self.model = model
        self._usage = usage

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._client.embed(texts, usage=self._usage)


@asynccontextmanager
async def embedder_scope(usage: UsageContext | None = None) -> AsyncIterator[EmbeddingProvider]:
    settings = get_settings()
    if settings.openai_api_key is None:
        if settings.environment not in (Environment.LOCAL, Environment.TEST):
            raise ProviderNotConfiguredError("OPENAI_API_KEY is not configured")
        yield HashEmbeddingProvider()
        return
    client = embedding_client_from_settings()
    try:
        yield OpenAIEmbeddingProvider(client, settings.embedding_model, usage)
    finally:
        await client.aclose()


@asynccontextmanager
async def mapper_scope() -> AsyncIterator[ConceptMapper]:
    if get_settings().openrouter_api_key is None:
        yield KeywordConceptMapper()
        return
    llm = llm_client_from_settings()
    try:
        yield LLMConceptMapper(llm)
    finally:
        await llm.aclose()
