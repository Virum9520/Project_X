"""Embedder and mapper wiring: hash vectors stay out of hosted environments."""

import pytest
from pydantic import SecretStr

from sg_core.knowledge import KeywordConceptMapper, LLMConceptMapper
from sg_core.knowledge.providers import OpenAIEmbeddingProvider, embedder_scope, mapper_scope
from sg_core.memory.embeddings import HashEmbeddingProvider
from sg_core.providers import ProviderNotConfiguredError
from sg_core.settings import Environment, Settings


def use_settings(monkeypatch: pytest.MonkeyPatch, **values: object) -> None:
    settings = Settings(_env_file=None, **values)  # type: ignore[call-arg]
    monkeypatch.setattr("sg_core.knowledge.providers.get_settings", lambda: settings)


async def test_local_without_keys_uses_offline_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    use_settings(monkeypatch, environment=Environment.LOCAL)
    async with embedder_scope() as embedder, mapper_scope() as mapper:
        assert isinstance(embedder, HashEmbeddingProvider)
        assert isinstance(mapper, KeywordConceptMapper)


async def test_hosted_environment_refuses_hash_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    use_settings(monkeypatch, environment=Environment.PROD)
    with pytest.raises(ProviderNotConfiguredError):
        async with embedder_scope():
            raise AssertionError("must not yield a provider")


async def test_keys_select_the_real_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = {
        "environment": Environment.PROD,
        "openai_api_key": SecretStr("sk-test"),
        "openrouter_api_key": SecretStr("or-test"),
    }
    use_settings(monkeypatch, **keys)
    monkeypatch.setattr("sg_core.settings.get_settings", lambda: Settings(_env_file=None, **keys))  # type: ignore[call-arg]
    async with embedder_scope() as embedder, mapper_scope() as mapper:
        assert isinstance(embedder, OpenAIEmbeddingProvider)
        assert embedder.model == "text-embedding-3-small"
        assert isinstance(mapper, LLMConceptMapper)
