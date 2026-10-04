"""Live `record_observation`: store the agent's note as evidence and show provisional glow.

The agent proposes ("the learner explained it, no hints"). We never take that at face value:
a fast micro-judge grades the quoted answer against the concept rubric in a few seconds, and
only a positive grade shows *provisional* growth (a glowing, clearly-labelled memory the garden
UI renders ghosted). Nothing here touches `plant_states` or `garden_revisions`; the post-call
pipeline confirms or retracts the glow, and the rules engine alone changes the garden.

The learner is never told what was decided (the tool result is neutral), and `communication`
observations are kept as provisional memories only: that dimension never grows a plant.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sg_core.economics.usage import UsageContext
from sg_core.evidence.judge import MicroJudge
from sg_core.evidence.store import EvidenceStore, NewEvidence, SessionRef
from sg_core.evidence.transcript import clean_text, looks_like_injection, normalize
from sg_core.evidence.types import MicroVerdict
from sg_core.memory import NewMemory
from sg_core.models.enums import (
    AssessmentOutcome,
    Assistance,
    Character,
    CostCenter,
    MemoryLayer,
    MemorySource,
    MemoryStatus,
)

MAX_QUOTE_WORDS = 120  # the tool asks for under 60; tolerate a little, refuse essays
MAX_GLOW_UNCERTAINTY = 0.5
TOOL_DIMENSIONS = ("explanation", "application", "transfer", "retention", "communication")
TOOL_OUTCOMES = ("correct", "partially_correct", "incorrect", "no_attempt")
TOOL_ASSISTANCE = ("independent", "hinted", "heavily_assisted")
PROVISIONAL_KIND = "provisional_growth"
_SLUG = re.compile(r"[^a-z0-9_.\-]+")


class ObservationRejectedError(ValueError):
    """The observation cannot be recorded; `code` is stable for the tool response."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ObservationInput:
    concept_id: str
    dimension: str
    outcome: str
    assistance: str
    evidence_quote: str
    question_id: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ObservationOutcome:
    status: Literal["recorded", "already_recorded"]
    glow: bool
    evidence_id: uuid.UUID | None
    memory_id: uuid.UUID | None
    micro: MicroVerdict | None = None


def _slug(value: str | None) -> str | None:
    if not value:
        return None
    slug = _SLUG.sub("_", value.strip().lower())[:64].strip("_")
    return slug or None


async def record_observation(
    store: EvidenceStore,
    micro: MicroJudge | None,
    *,
    session: SessionRef,
    obs: ObservationInput,
    now: datetime,
) -> ObservationOutcome:
    catalog = await store.catalog()
    concept = catalog.get(obs.concept_id)
    if concept is None:
        raise ObservationRejectedError("unknown_concept", "concept_id is not in the curriculum")
    if obs.dimension not in TOOL_DIMENSIONS:
        raise ObservationRejectedError("unknown_dimension", "unsupported dimension")
    if obs.outcome not in TOOL_OUTCOMES or obs.assistance not in TOOL_ASSISTANCE:
        raise ObservationRejectedError("invalid_value", "outcome or assistance is not valid")
    quote = " ".join(clean_text(obs.evidence_quote).split())
    if not quote:
        raise ObservationRejectedError("missing_quote", "evidence_quote is required")
    if len(quote.split()) > MAX_QUOTE_WORDS:
        raise ObservationRejectedError("quote_too_long", "keep evidence_quote under 60 words")

    assistance = Assistance.INDEPENDENT if obs.assistance == "independent" else Assistance.ASSISTED
    conv = session.conversation_id or str(session.id)
    digest = hashlib.sha256(
        f"{obs.concept_id}|{obs.dimension}|{obs.question_id}|{normalize(quote)}".encode()
    ).hexdigest()[:16]
    character = Character(session.character) if session.character in list(Character) else None
    base = {
        "concept_key": obs.concept_id,
        "dimension": obs.dimension,
        "assistance": assistance.value,
        "agent_outcome": obs.outcome,
        "question_id": obs.question_id,
        "source": "record_observation",
    }

    if obs.dimension == "communication":
        # Not a plant dimension: provisional memory only, so Vidura's report can use it.
        memory_id = await store.append_memory(
            NewMemory(
                user_id=session.user_id,
                layer=MemoryLayer.SKILLS,
                kind="communication_observation",
                content=f"{concept.title}: {obs.note or obs.outcome}. Learner said: {quote}"[:1000],
                source=MemorySource.AGENT,
                source_character=character,
                source_session_id=session.id,
                status=MemoryStatus.PROVISIONAL,
                data=base,
            )
        )
        return ObservationOutcome("recorded", False, None, memory_id)

    evidence_id = await store.add_evidence(
        session.user_id,
        session.id,
        NewEvidence(
            concept_key=obs.concept_id,
            dimension=obs.dimension,
            assistance=assistance,
            kind="live_quote",  # the agent's quote: unverified until the post-call judge checks it
            quote=quote,
            occurred_at=now,
            dedupe_key=f"ro:{conv}:{digest}"[:256],
            problem_family=_slug(obs.question_id),
        ),
    )
    existing = await store.provisional_memories(session.id)
    already = any(
        m.concept_key == obs.concept_id and m.dimension == obs.dimension for m in existing
    )
    if already:
        return ObservationOutcome("already_recorded", False, evidence_id, None)

    verdict: MicroVerdict | None = None
    if (
        micro is not None
        and obs.outcome != "no_attempt"
        and not looks_like_injection(quote)  # a quote that addresses the grader earns no glow
    ):
        verdict = await micro.grade(
            concept,
            obs.dimension,
            quote,
            usage=UsageContext(
                cost_center=CostCenter.LEARNER,
                component="evidence.micro_judge",
                user_id=session.user_id,
                session_id=session.id,
                idempotency_key=f"micro:{conv}:{digest}",
            ),
        )
    glow = (
        verdict is not None
        and verdict.outcome in (AssessmentOutcome.DEMONSTRATED, AssessmentOutcome.PARTIAL)
        and verdict.uncertainty <= MAX_GLOW_UNCERTAINTY
    )
    if not glow:
        await store.emit(
            session.id,
            session.user_id,
            "observation.recorded",
            {"concept": obs.concept_id, "dimension": obs.dimension},
        )
        return ObservationOutcome("recorded", False, evidence_id, None, verdict)

    assert verdict is not None
    memory_id = await store.append_memory(
        NewMemory(
            user_id=session.user_id,
            layer=MemoryLayer.SKILLS,
            kind=PROVISIONAL_KIND,
            content=(
                f"Live: {concept.title} {obs.dimension} looks {verdict.outcome.value} "
                f"({assistance.value}). Awaiting the full review."
            ),
            source=MemorySource.AGENT,
            source_character=character,
            source_session_id=session.id,
            evidence_ids=[evidence_id],
            status=MemoryStatus.PROVISIONAL,
            confidence=round(1 - verdict.uncertainty, 3),
            data={
                **base,
                "outcome": verdict.outcome.value,
                "micro_model": verdict.model,
                "glow": True,
            },
        )
    )
    await store.emit(
        session.id,
        session.user_id,
        "garden.provisional_growth",
        {
            "concept": obs.concept_id,
            "dimension": obs.dimension,
            "assistance": assistance.value,
            "outcome": verdict.outcome.value,
            "memory_id": str(memory_id),
            "evidence_id": str(evidence_id),
        },
    )
    return ObservationOutcome("recorded", True, evidence_id, memory_id, verdict)
