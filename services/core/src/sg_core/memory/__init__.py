"""Memory Persistence Engine (C09): append-only memories, session briefings and projections."""

from sg_core.memory.briefing import Briefing, build_briefing
from sg_core.memory.embeddings import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    get_embedding_provider,
    set_embedding_provider,
)
from sg_core.memory.errors import MemoryEngineError, MemoryNotFound, MemoryRuleViolation
from sg_core.memory.projections import (
    AnalyticsSummary,
    GardenView,
    GrowthEvent,
    analytics_summary,
    garden_view,
    growth_events,
    uncited_growth,
)
from sg_core.memory.store import MemoryStore, NewMemory

__all__ = [
    "AnalyticsSummary",
    "Briefing",
    "EmbeddingProvider",
    "GardenView",
    "GrowthEvent",
    "HashEmbeddingProvider",
    "MemoryEngineError",
    "MemoryNotFound",
    "MemoryRuleViolation",
    "MemoryStore",
    "NewMemory",
    "analytics_summary",
    "build_briefing",
    "garden_view",
    "get_embedding_provider",
    "growth_events",
    "set_embedding_provider",
    "uncited_growth",
]
