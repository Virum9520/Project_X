"""Plain data shared by the evidence pipeline. No I/O and no database types."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sg_core.models.enums import AssessmentOutcome, Assistance, Dimension

Role = Literal["agent", "learner"]

# Dimensions the judge may assess. `communication` is judged elsewhere and never grows a plant.
JUDGED_DIMENSIONS: tuple[str, ...] = tuple(d.value for d in Dimension)


@dataclass(frozen=True, slots=True)
class ToolEvent:
    """A tool call the agent made during a turn (data only; never executed here)."""

    name: str
    params: dict[str, Any]
    result: str | None = None


@dataclass(frozen=True, slots=True)
class Turn:
    index: int
    role: Role
    text: str
    time_s: float | None = None
    tools: tuple[ToolEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class Transcript:
    """A provider transcript, normalised. Everything in `turns` is untrusted data."""

    conversation_id: str
    turns: tuple[Turn, ...]
    started_at: datetime | None = None
    duration_s: float | None = None
    status: str | None = None
    dynamic_variables: dict[str, str] = field(default_factory=dict)

    def turn(self, index: int) -> Turn | None:
        for t in self.turns:
            if t.index == index:
                return t
        return None

    def learner_turns(self) -> tuple[Turn, ...]:
        return tuple(t for t in self.turns if t.role == "learner")


@dataclass(frozen=True, slots=True)
class AgentObservation:
    """What the agent claimed via `record_observation`. A hint, never evidence on its own."""

    concept_key: str
    dimension: str
    assistance: str  # independent | hinted | heavily_assisted
    outcome: str  # correct | partially_correct | incorrect | no_attempt
    question_id: str | None = None
    evidence_quote: str | None = None

    @property
    def assisted(self) -> bool:
        return self.assistance != "independent"


@dataclass(frozen=True, slots=True)
class RubricInfo:
    id: uuid.UUID | None
    version: int | None
    criteria: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ConceptInfo:
    id: uuid.UUID
    key: str
    title: str
    domain: str
    summary: str | None = None
    rubric: RubricInfo | None = None


@dataclass(frozen=True, slots=True)
class Citation:
    """A verified pointer into the transcript: the learner's own words in one turn."""

    turn: int
    quote: str


@dataclass(frozen=True, slots=True)
class RawVerdict:
    """What a judge returned for one concept and dimension, before validation."""

    concept_key: str
    dimension: str
    outcome: str
    assistance: str
    citations: tuple[tuple[int, str], ...]  # (turn index, quote)
    rationale: str
    uncertainty: float | None = None
    problem_family: str | None = None
    misconception: str | None = None


@dataclass(frozen=True, slots=True)
class Verdict:
    """A validated verdict: every field checked, every citation found in a learner turn."""

    concept_key: str
    dimension: str
    outcome: AssessmentOutcome
    assistance: Assistance
    citations: tuple[Citation, ...]
    rationale: str
    uncertainty: float | None
    problem_family: str | None = None
    misconception: str | None = None
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Rejection:
    concept_key: str | None
    dimension: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class MicroVerdict:
    """The fast provisional grade of one answer. Provisional: never changes the garden."""

    outcome: AssessmentOutcome
    uncertainty: float
    rationale: str
    model: str


@dataclass(slots=True)
class PipelineResult:
    status: Literal["judged", "no_candidates", "unchanged", "empty_transcript"]
    session_id: uuid.UUID | None = None
    revision: int | None = None
    assessments: int = 0
    accepted: int = 0
    rejected: list[Rejection] = field(default_factory=list)
    reassess: int = 0
    confirmed: int = 0
    retracted: int = 0
    detail: str | None = None
