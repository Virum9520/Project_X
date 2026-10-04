"""Embedding provider seam for memories.

C03 (provider adapters) supplies the real OpenAI-backed provider and installs it with
`set_embedding_provider`. Until then a deterministic hashing provider keeps the engine usable in
development and tests. Vectors from different models are never compared: similarity queries
filter on `memories.embedding_model`.
"""

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol

from sg_core.models.base import EMBEDDING_DIM

_TOKEN = re.compile(r"[a-z0-9]+")


class EmbeddingProvider(Protocol):
    model: str

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashEmbeddingProvider:
    """Bag-of-words feature hashing into `EMBEDDING_DIM` dimensions, L2-normalised.

    Deterministic and offline. Texts that share words are close, which is enough for tests and
    local development. Not a semantic model.
    """

    model = "hash-bow-v1"

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._one(text) for text in texts]

    @staticmethod
    def _one(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIM
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIM
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return vector
        return [v / norm for v in vector]


_provider: EmbeddingProvider = HashEmbeddingProvider()


def get_embedding_provider() -> EmbeddingProvider:
    return _provider


def set_embedding_provider(provider: EmbeddingProvider) -> None:
    """Install the process-wide provider (C03 calls this at startup)."""
    global _provider
    _provider = provider
