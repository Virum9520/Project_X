"""Wire models. They mirror `packages/contracts` (`GardenSnapshot` in `index.ts`, `GardenDataset`
in `garden.ts`); field names are camelCase on the wire."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ── GardenSnapshot (the read model the 3D scene renders) ──
class DimensionScoreOut(Wire):
    independent: float = 0.0
    assisted: float = 0.0


class GroveSnapshotOut(Wire):
    id: str
    label: str


class PlantSnapshotOut(Wire):
    concept_id: str  # the stable concept key, e.g. `dsa.bfs`
    grove_id: str
    label: str
    status: str
    dimensions: dict[str, DimensionScoreOut]
    provisional: dict[str, float] | None = None
    evidence_count: int = 0
    last_evidence_at: str | None = None
    next_review_at: str | None = None


class PrerequisiteEdgeOut(Wire):
    from_: str = Field(alias="from")
    to: str


class GardenSnapshotOut(Wire):
    revision: int
    rule_version: str
    created_at: str
    groves: list[GroveSnapshotOut]
    plants: list[PlantSnapshotOut]
    prerequisites: list[PrerequisiteEdgeOut]


class RevisionOut(Wire):
    rev: int
    rule_version: str
    reason: str
    created_at: str


# ── GardenDataset (everything the dashboard renders) ──
class GroveOut(Wire):
    id: str
    title: str


class PlantMetaOut(Wire):
    key: str
    title: str
    grove: str
    difficulty: int


class EvidenceOut(Wire):
    id: str
    plant_key: str
    dimension: str
    kind: Literal["independent", "assisted"]
    character: str
    session_id: str
    occurred_at: str
    quote: str
    source: Literal["transcript", "code", "tests"]
    rationale: str
    assist_note: str | None = None
    confidence: float
    weight: float
    rubric_version: str
    status: Literal["provisional", "confirmed"]


class GrowthEventOut(Wire):
    id: str
    plant_key: str
    occurred_at: str
    dimension: str
    from_stage: str
    to_stage: str
    summary: str
    evidence_ids: list[str] = Field(min_length=1)
    revision: int


class SessionMarkerOut(Wire):
    id: str
    character: str
    started_at: str
    minutes: int
    title: str
    evidence_ids: list[str]


class MemoryOut(Wire):
    id: str
    character: str
    layer: str
    text: str
    why: str
    status: Literal["provisional", "accepted", "disputed"]
    confidence: float
    evidence_ids: list[str]
    affects: list[str]
    deletable: bool
    created_at: str


class MisconceptionOut(Wire):
    id: str
    plant_key: str
    text: str
    occurrences: int
    last_seen_at: str
    evidence_ids: list[str] = Field(min_length=1)


class NextBestOut(Wire):
    character: str
    plant_key: str
    title: str
    reason: str
    minutes: int
    evidence_ids: list[str]


class ReadinessModelOut(Wire):
    version: str
    target_role: str
    dimension_weights: dict[str, float]


class FreshnessOut(Wire):
    projection_at: str
    rules_version: str
    curriculum: str


class GardenDatasetOut(Wire):
    generated_at: str
    freshness: FreshnessOut
    readiness: ReadinessModelOut
    groves: list[GroveOut]
    plants: list[PlantMetaOut]
    evidence: list[EvidenceOut]
    growth_events: list[GrowthEventOut]
    sessions: list[SessionMarkerOut]
    memories: list[MemoryOut]
    misconceptions: list[MisconceptionOut]
    next_best: list[NextBestOut]
    streak_days: int
    prerequisites: list[PrerequisiteEdgeOut] = []


# ── Analytics, memory routes, Ask Sanjaya ──
class AnalyticsOut(Wire):
    metric: str
    as_of: str
    rules_version: str
    data: dict[str, Any]
    citations: list[str]


class CorrectMemoryIn(Wire):
    content: str = Field(min_length=1, max_length=2000)


class MemoryImpactOut(Wire):
    memory_id: str
    affects: list[str]


class AskIn(Wire):
    question: str = Field(min_length=1, max_length=500)


class AskOut(Wire):
    answer: str
    citations: list[str]
    metrics: list[str]
    # False when the model was unavailable and the answer was composed from the numbers alone.
    grounded: bool
