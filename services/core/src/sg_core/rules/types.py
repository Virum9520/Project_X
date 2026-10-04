"""Immutable inputs and outputs of the rules engine. No I/O, no database types."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sg_core.models.enums import AssessmentOutcome, Assistance, Dimension, PlantStatus

ENGINE_VERSION = "1"

# Dimensions that grow a plant. Anything else (notably `communication`, see rules/README.md)
# is accepted as evidence elsewhere but never changes the garden.
GROWTH_DIMENSIONS: tuple[str, ...] = tuple(d.value for d in Dimension)

SkipReason = Literal[
    "duplicate_assessment",
    "no_evidence",
    "unknown_concept",
    "non_growth_dimension",
    "unknown_dimension",
    "unassessable",
    "no_credit",
    "repeat_problem_family",
    "missing_problem_family",
    "same_family_as_application",
    "assisted_retention_not_counted",
    "retention_before_learning",
    "retention_too_soon",
    "out_of_order",
]


@dataclass(frozen=True, slots=True)
class Observation:
    """One accepted assessment, the engine's unit of input.

    `evidence_ids` are the evidence items the judge cited; growth without them is refused.
    """

    assessment_id: uuid.UUID
    concept_key: str
    dimension: str  # a `Dimension` value, or e.g. "communication" (never grows a plant)
    outcome: AssessmentOutcome
    assistance: Assistance
    occurred_at: datetime
    evidence_ids: tuple[uuid.UUID, ...]
    uncertainty: float | None = None
    problem_family: str | None = None


@dataclass(frozen=True, slots=True)
class DimensionState:
    """Independent and assisted progress are separate tracks and never merge."""

    independent: float = 0.0
    assisted: float = 0.0
    # Counted problem families, prefixed `i:` (independent) or `a:` (assisted); sorted.
    families: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlantState:
    concept_key: str
    dimensions: dict[str, DimensionState] = field(default_factory=dict)
    status: PlantStatus = PlantStatus.UNASSESSED  # includes the DUE/WILTING overlay
    review_step: int = 0
    last_evidence_at: datetime | None = None
    last_learning_at: datetime | None = None  # last independent explanation/application/transfer
    next_review_at: datetime | None = None

    def dimension(self, name: str) -> DimensionState:
        return self.dimensions.get(name, DimensionState())

    def to_scores(self) -> dict[str, Any]:
        """JSON for `plant_states.dimension_scores` (`_review` carries the scheduling state)."""
        scores: dict[str, Any] = {
            name: {
                "independent": s.independent,
                "assisted": s.assisted,
                "families": list(s.families),
            }
            for name, s in sorted(self.dimensions.items())
        }
        scores["_review"] = {
            "step": self.review_step,
            "last_learning_at": self.last_learning_at.isoformat()
            if self.last_learning_at
            else None,
        }
        return scores

    @classmethod
    def from_row(
        cls,
        concept_key: str,
        *,
        status: PlantStatus,
        dimension_scores: dict[str, Any],
        last_evidence_at: datetime | None,
        next_review_at: datetime | None,
    ) -> "PlantState":
        review = dimension_scores.get("_review") or {}
        learned = review.get("last_learning_at")
        dims = {
            name: DimensionState(
                float(v.get("independent", 0.0)),
                float(v.get("assisted", 0.0)),
                tuple(v.get("families", ())),
            )
            for name, v in dimension_scores.items()
            if name in GROWTH_DIMENSIONS
        }
        return cls(
            concept_key=concept_key,
            dimensions=dims,
            status=status,
            review_step=int(review.get("step", 0)),
            last_evidence_at=last_evidence_at,
            last_learning_at=datetime.fromisoformat(learned) if learned else None,
            next_review_at=next_review_at,
        )


@dataclass(frozen=True, slots=True)
class GardenState:
    plants: dict[str, PlantState] = field(default_factory=dict)
    # Assessments already applied (from `garden_revisions.assessment_ids`): replays are no-ops.
    applied: frozenset[uuid.UUID] = frozenset()


@dataclass(frozen=True, slots=True)
class Skipped:
    assessment_id: uuid.UUID
    reason: SkipReason


@dataclass(frozen=True, slots=True)
class GrowthEvent:
    """One cited change to a plant. `growth` adds to a track; `review_failed` resets the clock."""

    assessment_id: uuid.UUID
    evidence_ids: tuple[uuid.UUID, ...]
    dimension: str
    track: Assistance
    kind: Literal["growth", "review_passed", "review_failed"]
    before: float
    after: float

    def __post_init__(self) -> None:
        if not self.evidence_ids:
            raise ValueError("every garden growth event must cite evidence")


@dataclass(frozen=True, slots=True)
class PlantChange:
    concept_key: str
    reason: Literal["assessment", "decay"]
    status_before: PlantStatus
    status_after: PlantStatus
    before: PlantState | None
    after: PlantState
    events: tuple[GrowthEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class RulesResult:
    """Proposed garden changes. Persisting them (a `garden_revisions` row plus `plant_states`)
    is the caller's job (C11); the engine never touches storage."""

    rule_version: str  # store as `garden_revisions.rule_ver`
    profile_hash: str
    changes: tuple[PlantChange, ...]
    state: GardenState  # the garden after applying `changes`
    skipped: tuple[Skipped, ...] = ()
    reassess: tuple[uuid.UUID, ...] = ()  # ambiguous assessments to re-judge (no growth)
    # Every assessment consumed by this call (grew, or was a counted no-op); store on the revision.
    processed: tuple[uuid.UUID, ...] = ()

    @property
    def revision_reason(self) -> Literal["assessment", "decay"] | None:
        """`garden_revisions.reason`; None when there is nothing to commit."""
        if any(c.reason == "assessment" for c in self.changes):
            return "assessment"
        return "decay" if self.changes else None

    @property
    def assessment_ids(self) -> tuple[uuid.UUID, ...]:
        """For `garden_revisions.assessment_ids`: all consumed, so replays stay no-ops."""
        return self.processed

    def to_revision_changes(self) -> list[dict[str, Any]]:
        """JSON for `garden_revisions.changes`: per-concept before/after with citations."""
        return [
            {
                "concept": c.concept_key,
                "reason": c.reason,
                "status": {"before": c.status_before.value, "after": c.status_after.value},
                "scores": {
                    "before": c.before.to_scores() if c.before else None,
                    "after": c.after.to_scores(),
                },
                "events": [
                    {
                        "assessment_id": str(e.assessment_id),
                        "evidence_ids": [str(i) for i in e.evidence_ids],
                        "dimension": e.dimension,
                        "track": e.track.value,
                        "kind": e.kind,
                        "before": e.before,
                        "after": e.after,
                    }
                    for e in c.events
                ],
            }
            for c in self.changes
        ]
