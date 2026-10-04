"""Plain records for one learner's garden and the loader that fills them from the database.

The builders in `build` and `analytics` are pure functions over `GardenData`, so they are unit
tested without a database. Garden state itself comes from the `sg_core.memory` projections
(`garden_view`, `analytics_summary`); this module only adds what those do not carry.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.logging import get_logger
from sg_core.memory import MemoryStore, analytics_summary, garden_view
from sg_core.memory.projections import GardenView
from sg_core.models.curriculum import Concept, ConceptEdge, Curriculum
from sg_core.models.enums import ConceptEdgeKind, CurriculumStatus
from sg_core.models.evidence import Assessment, EvidenceItem, GardenRevision
from sg_core.models.identity import Profile, User
from sg_core.models.memory import Memory
from sg_core.models.sessions import Session as SessionRow

log = get_logger(__name__)

DEFAULT_TARGET_ROLE = "Software engineer"
EVIDENCE_CAP = 5000
SESSION_CAP = 1000
MEMORY_CAP = 100
REVISION_CAP = 500
# A learner who has no `users` row yet (signed in, not synced) sees an empty garden.
NO_USER = uuid.UUID(int=0)


@dataclass
class ConceptRec:
    id: uuid.UUID
    key: str
    domain: str
    title: str
    difficulty: int


@dataclass
class EvidenceRec:
    id: uuid.UUID
    concept_id: uuid.UUID
    session_id: uuid.UUID
    dimension: str
    assistance: str  # independent | assisted
    kind: str  # quote | answer | code_run | teach_back
    quote: str | None
    occurred_at: datetime
    hint_count: int = 0
    has_code: bool = False
    has_run: bool = False


@dataclass
class AssessmentRec:
    id: uuid.UUID
    concept_id: uuid.UUID
    session_id: uuid.UUID
    dimension: str
    outcome: str
    assistance: str
    score: float | None
    uncertainty: float | None
    rationale: str
    evidence_ids: list[uuid.UUID]
    status: str
    rubric_ver: int | None
    created_at: datetime


@dataclass
class SessionRec:
    id: uuid.UUID
    character: str
    mode: str
    status: str
    started_at: datetime
    duration_seconds: int | None


@dataclass
class MemoryRec:
    id: uuid.UUID
    layer: str
    kind: str
    content: str
    status: str
    source: str
    source_character: str | None
    confidence: float | None
    evidence_ids: list[uuid.UUID]
    data: dict[str, Any]
    created_at: datetime
    affects: list[str] = field(default_factory=list)


@dataclass
class RevisionRec:
    rev: int
    rule_ver: str
    reason: str
    created_at: datetime
    assessment_ids: list[uuid.UUID]
    changes: list[dict[str, Any]]


@dataclass
class GardenData:
    now: datetime
    view: GardenView
    concepts: dict[uuid.UUID, ConceptRec]
    edges: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)
    curriculum: str = "none"
    target_role: str = DEFAULT_TARGET_ROLE
    revisions: list[RevisionRec] = field(default_factory=list)
    evidence: list[EvidenceRec] = field(default_factory=list)
    assessments: list[AssessmentRec] = field(default_factory=list)
    sessions: list[SessionRec] = field(default_factory=list)
    memories: list[MemoryRec] = field(default_factory=list)
    # Practice minutes per UTC day, from sessions and the learner_analytics continuous aggregate.
    practice_minutes: dict[date, int] = field(default_factory=dict)
    streak_days: int = 0


def memory_rec(m: Memory, affects: list[str]) -> MemoryRec:
    return MemoryRec(
        id=m.id,
        layer=m.layer.value,
        kind=m.kind,
        content=m.content,
        status=m.status.value,
        source=m.source.value,
        source_character=m.source_character.value if m.source_character else None,
        confidence=m.confidence,
        evidence_ids=list(m.evidence_ids or []),
        data=dict(m.data or {}),
        created_at=m.created_at,
        affects=affects,
    )


async def resolve_user_id(session: AsyncSession, clerk_user_id: str) -> uuid.UUID | None:
    return await session.scalar(
        select(User.id).where(User.clerk_user_id == clerk_user_id, User.deleted_at.is_(None))
    )


async def load_practice_minutes(
    session: AsyncSession, user_id: uuid.UUID, since: datetime
) -> dict[date, int]:
    """Minutes practised per UTC day. Combines `sessions.duration_seconds` with the
    `learner_analytics.daily_session_activity` continuous aggregate (event span per session,
    which covers sessions that ended without a recorded duration). The larger figure wins."""
    minutes: dict[date, int] = {}
    rows = await session.execute(
        select(SessionRow.started_at, SessionRow.duration_seconds).where(
            SessionRow.user_id == user_id,
            SessionRow.started_at.is_not(None),
            SessionRow.started_at >= since,
        )
    )
    for started, seconds in rows:
        if started is not None and seconds:
            day = started.astimezone(UTC).date()
            minutes[day] = minutes.get(day, 0) + round(seconds / 60)
    try:
        async with session.begin_nested():  # a missing view must not poison the transaction
            cagg = await session.execute(
                text(
                    "SELECT (bucket AT TIME ZONE 'UTC')::date AS day, "
                    "round(sum(extract(epoch FROM last_event_at - first_event_at)) / 60)::int "
                    "FROM learner_analytics.daily_session_activity "
                    "WHERE user_id = :user_id AND bucket >= :since GROUP BY 1"
                ),
                {"user_id": user_id, "since": since},
            )
            for day, mins in cagg:
                minutes[day] = max(minutes.get(day, 0), int(mins or 0))
    except Exception:
        log.info("garden.cagg_unavailable", exc_info=True)
    return minutes


async def load_garden_data(
    session: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None
) -> GardenData:
    moment = now or datetime.now(UTC)
    view = await garden_view(session, user_id)
    concept_ids = [p.concept_id for p in view.plants]
    concepts = {
        c.id: ConceptRec(c.id, c.key, c.domain, c.title, c.difficulty or 1)
        for c in (await session.scalars(select(Concept).where(Concept.id.in_(concept_ids)))).all()
    }
    edges = [
        (a, b)
        for a, b in (
            await session.execute(
                select(ConceptEdge.from_concept_id, ConceptEdge.to_concept_id).where(
                    ConceptEdge.kind == ConceptEdgeKind.PREREQUISITE.value,
                    ConceptEdge.from_concept_id.in_(concept_ids),
                    ConceptEdge.to_concept_id.in_(concept_ids),
                )
            )
        ).all()
    ]
    curriculum = await session.scalar(
        select(Curriculum).where(Curriculum.status == CurriculumStatus.ACTIVE).limit(1)
    )
    target_role = await session.scalar(
        select(Profile.target_role).where(Profile.user_id == user_id)
    )

    revisions = [
        RevisionRec(r.rev, r.rule_ver, r.reason, r.created_at, list(r.assessment_ids), r.changes)
        for r in reversed(
            (
                await session.scalars(
                    select(GardenRevision)
                    .where(GardenRevision.user_id == user_id)
                    .order_by(GardenRevision.rev.desc())
                    .limit(REVISION_CAP)
                )
            ).all()
        )
    ]
    evidence = [
        EvidenceRec(
            id=e.id,
            concept_id=e.concept_id,
            session_id=e.session_id,
            dimension=e.dimension.value,
            assistance=e.assistance.value,
            kind=e.kind,
            quote=e.quote,
            occurred_at=e.occurred_at,
            hint_count=len(e.hint_ids or []),
            has_code=e.code_snapshot_id is not None,
            has_run=e.sandbox_run_id is not None,
        )
        for e in (
            await session.scalars(
                select(EvidenceItem)
                .where(EvidenceItem.user_id == user_id)
                .order_by(EvidenceItem.occurred_at.desc())
                .limit(EVIDENCE_CAP)
            )
        ).all()
    ]
    assessments = [
        AssessmentRec(
            id=a.id,
            concept_id=a.concept_id,
            session_id=a.session_id,
            dimension=a.dimension.value,
            outcome=a.outcome.value,
            assistance=a.assistance.value,
            score=a.score,
            uncertainty=a.uncertainty,
            rationale=a.rationale,
            evidence_ids=list(a.evidence_ids or []),
            status=a.status.value,
            rubric_ver=a.rubric_ver,
            created_at=a.created_at,
        )
        for a in (
            await session.scalars(select(Assessment).where(Assessment.user_id == user_id))
        ).all()
    ]
    sessions = [
        SessionRec(
            id=s.id,
            character=s.character.value,
            mode=s.mode,
            status=s.status.value,
            started_at=s.started_at or s.created_at,
            duration_seconds=s.duration_seconds,
        )
        for s in (
            await session.scalars(
                select(SessionRow)
                .where(SessionRow.user_id == user_id, SessionRow.is_test.is_(False))
                .order_by(SessionRow.created_at.desc())
                .limit(SESSION_CAP)
            )
        ).all()
    ]
    store = MemoryStore(session)
    memories = [
        memory_rec(m, await store.impact(m))
        for m in await store.list_active(user_id, limit=MEMORY_CAP)
    ]
    since = moment - timedelta(days=60)
    summary = await analytics_summary(session, user_id, now=moment)
    return GardenData(
        now=moment,
        view=view,
        concepts=concepts,
        edges=edges,
        curriculum=f"{curriculum.key}@{curriculum.version}" if curriculum else "none",
        target_role=target_role or DEFAULT_TARGET_ROLE,
        revisions=revisions,
        evidence=evidence,
        assessments=assessments,
        sessions=sessions,
        memories=memories,
        practice_minutes=await load_practice_minutes(session, user_id, since),
        streak_days=summary.streak_days,
    )
