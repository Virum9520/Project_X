"""Session briefing builder: a bounded, relevance-ranked view of what the system knows.

Sections, in priority order (later ones are dropped first when the budget runs out):
goals, focus concept, due reviews, open commitments, misconceptions, recent observations,
preferences and other memories. Memories are ranked by pgvector similarity to the session's
focus, recency and due-ness. Superseded and expired memories are excluded, private reflections
are filtered by `visible_to`, and independent evidence is shown apart from assisted evidence.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.logging import get_logger
from sg_core.memory.embeddings import EmbeddingProvider, get_embedding_provider
from sg_core.memory.ranking import Section, memory_line, render_briefing, sanitize, score_memory
from sg_core.memory.store import active_filter
from sg_core.models.accountability import Commitment
from sg_core.models.curriculum import Concept, Curriculum
from sg_core.models.enums import (
    Assistance,
    CommitmentStatus,
    CurriculumStatus,
    MemoryLayer,
    PlantStatus,
)
from sg_core.models.evidence import EvidenceItem, PlantState
from sg_core.models.identity import Profile
from sg_core.models.memory import Memory

log = get_logger(__name__)

DEFAULT_MAX_CHARS = 4000
DEFAULT_TARGET_ROLE = "Software Engineer"
_CANDIDATES_BY_SIMILARITY = 40
_CANDIDATES_BY_RECENCY = 20
_MEMORIES_PER_SECTION = 5


@dataclass
class Briefing:
    text: str
    focus_concept: str = "none"
    focus_concept_title: str = "today's topic"
    due_concepts: list[str] = field(default_factory=list)
    target_role: str = DEFAULT_TARGET_ROLE
    memory_ids: list[uuid.UUID] = field(default_factory=list)


def _title_from_key(key: str) -> str:
    return key.rsplit(".", 1)[-1].replace("_", " ").capitalize()


def _scores_line(scores: dict[str, object]) -> str:
    """`{"explanation": {"independent": .6, "assisted": .8}}` -> separate independent and
    assisted figures, never blended."""
    parts: list[str] = []
    for dimension, value in sorted(scores.items()):
        if not isinstance(value, dict):
            continue
        independent = value.get("independent")
        assisted = value.get("assisted")
        bits = []
        if isinstance(independent, int | float):
            bits.append(f"independent {independent:.2f}")
        if isinstance(assisted, int | float):
            bits.append(f"assisted {assisted:.2f}")
        if bits:
            parts.append(f"{sanitize(dimension, 40)}: {', '.join(bits)}")
    return "; ".join(parts) or "no scored dimensions yet"


async def build_briefing(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    character: str,
    focus_concept_key: str | None = None,
    query_hint: str | None = None,
    embedder: EmbeddingProvider | None = None,
    now: datetime | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Briefing:
    moment = now or datetime.now(UTC)
    embedder = embedder or get_embedding_provider()

    profile = await session.get(Profile, user_id)
    target_role = (profile.target_role if profile and profile.target_role else None) or (
        DEFAULT_TARGET_ROLE
    )

    focus_title = "today's topic"
    focus_summary: str | None = None
    focus_concept: Concept | None = None
    if focus_concept_key:
        focus_title = _title_from_key(focus_concept_key)
        focus_concept = await session.scalar(
            select(Concept)
            .join(Curriculum, Curriculum.id == Concept.curriculum_id)
            .where(Concept.key == focus_concept_key, Curriculum.status == CurriculumStatus.ACTIVE)
        )
        if focus_concept is not None:
            focus_title = focus_concept.title
            focus_summary = focus_concept.summary

    sections: list[Section] = []

    # Goals and profile claims. Claims never establish mastery, so say so on the line.
    goals = Section("Learner goals (self-reported, not evidence of mastery)")
    if profile is not None:
        if profile.target_role:
            goals.lines.append(f"- Target role: {sanitize(profile.target_role, 120)}")
        if profile.major or profile.experience_level:
            bits = [b for b in (profile.major, profile.experience_level) if b]
            goals.lines.append(f"- Background: {sanitize(', '.join(bits), 160)}")
        goals.lines.extend(f"- Goal: {sanitize(str(g), 160)}" for g in (profile.goals or [])[:4])
    sections.append(goals)

    # Focus concept: independent evidence shown apart from assisted.
    focus = Section(f"Focus concept: {sanitize(focus_title, 120)}")
    if focus_concept is not None:
        plant = await session.get(PlantState, (user_id, focus_concept.id))
        if plant is not None and plant.status is not PlantStatus.UNASSESSED:
            focus.lines.append(f"- Garden status: {plant.status.value}")
            focus.lines.append(f"- Scores: {_scores_line(plant.dimension_scores)}")
        counts = dict(
            (
                await session.execute(
                    select(EvidenceItem.assistance, func.count())
                    .where(
                        EvidenceItem.user_id == user_id,
                        EvidenceItem.concept_id == focus_concept.id,
                    )
                    .group_by(EvidenceItem.assistance)
                )
            ).all()
        )
        independent = counts.get(Assistance.INDEPENDENT, 0)
        assisted = counts.get(Assistance.ASSISTED, 0)
        if independent or assisted:
            focus.lines.append(f"- Evidence so far: {independent} independent, {assisted} assisted")
    sections.append(focus)

    # Due reviews.
    due_rows = (
        await session.execute(
            select(Concept.key, Concept.title, PlantState.status, PlantState.next_review_at)
            .join(PlantState, PlantState.concept_id == Concept.id)
            .where(
                PlantState.user_id == user_id,
                or_(
                    PlantState.status.in_([PlantStatus.DUE.value, PlantStatus.WILTING.value]),
                    PlantState.next_review_at <= moment,
                ),
            )
            .order_by(PlantState.next_review_at.asc().nulls_last())
            .limit(8)
        )
    ).all()
    due_keys = {row.key for row in due_rows}
    due = Section("Reviews due")
    due.lines.extend(
        f"- {sanitize(row.title, 120)} ({row.key}, {row.status.value})" for row in due_rows
    )
    sections.append(due)

    # Open commitments, as the learner stated them (self-reported until verified).
    commitments = (
        await session.scalars(
            select(Commitment)
            .where(Commitment.user_id == user_id, Commitment.status == CommitmentStatus.OPEN)
            .order_by(Commitment.due_at.asc().nulls_last())
            .limit(5)
        )
    ).all()
    open_commitments = Section("Open commitments")
    for c in commitments:
        due_text = f", due {c.due_at:%Y-%m-%d}" if c.due_at else ""
        open_commitments.lines.append(f'- "{sanitize(c.description, 200)}"{due_text}')
    sections.append(open_commitments)

    # Ranked memories.
    ranked = await _ranked_memories(
        session,
        user_id=user_id,
        character=character,
        query_text=" ".join(
            part for part in (focus_title, focus_summary, query_hint, target_role) if part
        ),
        embedder=embedder,
        now=moment,
        due_keys=due_keys,
    )
    used: list[uuid.UUID] = []

    def take(title: str, kinds: set[str] | None, exclude: bool = False) -> Section:
        section = Section(title)
        for memory in ranked:
            if memory.id in used or len(section.lines) >= _MEMORIES_PER_SECTION:
                continue
            if kinds is not None and (memory.kind in kinds) is exclude:
                continue
            if memory.layer is MemoryLayer.PROFILE and exclude:
                continue  # profile claims are already in the goals section
            section.lines.append(
                memory_line(
                    kind=memory.kind,
                    status=memory.status,
                    when=memory.created_at,
                    source=memory.source.value,
                    content=memory.content,
                )
            )
            used.append(memory.id)
        return section

    sections.append(take("Known misconceptions (provisional until re-observed)", {"misconception"}))
    sections.append(take("Recent observations", {"observation"}))
    sections.append(take("Preferences", {"preference"}))
    sections.append(
        take(
            "Other relevant memories", {"misconception", "observation", "preference"}, exclude=True
        )
    )

    return Briefing(
        text=render_briefing(sections, max_chars),
        focus_concept=focus_concept_key or "none",
        focus_concept_title=focus_title,
        due_concepts=[row.title for row in due_rows],
        target_role=target_role,
        memory_ids=used,
    )


async def _ranked_memories(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    character: str,
    query_text: str,
    embedder: EmbeddingProvider,
    now: datetime,
    due_keys: set[str],
) -> list[Memory]:
    clauses = active_filter(user_id, character, now)
    similarity: dict[uuid.UUID, float] = {}
    candidates: dict[uuid.UUID, Memory] = {}

    try:
        [query_vector] = await embedder.embed([query_text])
    except Exception:  # fall back to recency and due-ness
        log.warning("briefing.embed_failed", exc_info=True)
        query_vector = None

    if query_vector is not None:
        distance = Memory.embedding.cosine_distance(query_vector)
        rows = await session.execute(
            select(Memory, distance)
            .where(
                *clauses, Memory.embedding.is_not(None), Memory.embedding_model == embedder.model
            )
            .order_by(distance)
            .limit(_CANDIDATES_BY_SIMILARITY)
        )
        for memory, dist in rows:
            candidates[memory.id] = memory
            similarity[memory.id] = 1.0 - float(dist)

    recent = await session.scalars(
        select(Memory)
        .where(*clauses)
        .order_by(Memory.created_at.desc())
        .limit(_CANDIDATES_BY_RECENCY)
    )
    for memory in recent:
        candidates.setdefault(memory.id, memory)

    def rank(memory: Memory) -> float:
        age = (now - memory.created_at).total_seconds() / 86400
        concept_key = memory.data.get("concept_key")
        return score_memory(
            similarity=similarity.get(memory.id),
            age_days=age,
            status=memory.status,
            confidence=memory.confidence,
            due=isinstance(concept_key, str) and concept_key in due_keys,
        )

    return sorted(candidates.values(), key=rank, reverse=True)
