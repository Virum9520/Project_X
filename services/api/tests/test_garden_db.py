"""`DbGardenService` against a real database at DATABASE_URL (schema at head).

Opt-in with `SG_DB_TESTS=1`. All writes (including the service's own commits) land in a
transaction that is rolled back at the end.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from sg_api.garden.analytics import make_query
from sg_api.garden.service import DbGardenService
from sg_core.memory import MemoryNotFound, MemoryRuleViolation
from sg_core.models.curriculum import Concept, ConceptEdge, Curriculum
from sg_core.models.enums import (
    AssessmentOutcome,
    AssessmentStatus,
    Assistance,
    Character,
    ConceptEdgeKind,
    CurriculumStatus,
    Dimension,
    MemoryLayer,
    MemorySource,
    MemoryStatus,
    PlantStatus,
)
from sg_core.models.evidence import Assessment, EvidenceItem, GardenRevision, PlantState
from sg_core.models.identity import Profile, User
from sg_core.models.memory import Memory
from sg_core.models.sessions import Session as SessionRow
from sg_core.settings import get_settings

pytestmark = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)

NOW = datetime.now(UTC)


@pytest.fixture
async def maker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(get_settings().database_url.unicode_string(), poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield async_sessionmaker(
                bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
            )
        finally:
            await transaction.rollback()
    await engine.dispose()


class World:
    clerk_id: str
    user_id: uuid.UUID
    other_clerk_id: str
    bfs: Concept
    graphs: Concept
    evidence_id: uuid.UUID
    private_id: uuid.UUID
    profile_id: uuid.UUID


async def _world(maker: async_sessionmaker[AsyncSession]) -> World:
    w = World()
    tag = uuid.uuid4().hex[:8]
    w.clerk_id, w.other_clerk_id = f"clerk_g_{tag}", f"clerk_o_{tag}"
    async with maker() as db, db.begin():
        user = User(clerk_user_id=w.clerk_id, email=f"{tag}@t.dev")
        other = User(clerk_user_id=w.other_clerk_id, email=f"o{tag}@t.dev")
        db.add_all([user, other])
        await db.flush()
        w.user_id = user.id
        db.add(Profile(user_id=user.id, target_role="Backend engineer"))
        curriculum = Curriculum(
            key=f"t-{tag}",
            version="v1",
            title="t",
            status=CurriculumStatus.ACTIVE,
            content_hash="h",
        )
        db.add(curriculum)
        await db.flush()
        w.bfs = Concept(
            curriculum_id=curriculum.id,
            key=f"dsa.bfs_{tag}",
            domain="dsa",
            title="BFS",
            difficulty=3,
        )
        w.graphs = Concept(
            curriculum_id=curriculum.id,
            key=f"dsa.graphs_{tag}",
            domain="dsa",
            title="Graphs",
            difficulty=3,
        )
        db.add_all([w.bfs, w.graphs])
        await db.flush()
        db.add(
            ConceptEdge(
                from_concept_id=w.graphs.id,
                to_concept_id=w.bfs.id,
                kind=ConceptEdgeKind.PREREQUISITE,
            )
        )
        session_row = SessionRow(
            user_id=user.id,
            character=Character.DRONA,
            mode="concept_exam",
            started_at=NOW - timedelta(hours=1),
            duration_seconds=1200,
        )
        db.add(session_row)
        await db.flush()
        evidence = EvidenceItem(
            user_id=user.id,
            session_id=session_row.id,
            concept_id=w.bfs.id,
            dimension=Dimension.EXPLANATION,
            assistance=Assistance.INDEPENDENT,
            kind="quote",
            quote="level by level with a queue",
            dedupe_key=f"d-{tag}",
            occurred_at=NOW - timedelta(minutes=50),
        )
        db.add(evidence)
        await db.flush()
        w.evidence_id = evidence.id
        assessment = Assessment(
            user_id=user.id,
            session_id=session_row.id,
            concept_id=w.bfs.id,
            dimension=Dimension.EXPLANATION,
            outcome=AssessmentOutcome.DEMONSTRATED,
            assistance=Assistance.INDEPENDENT,
            score=0.9,
            uncertainty=0.1,
            rationale="Correct and complete.",
            evidence_ids=[evidence.id],
            judge_model="test",
            status=AssessmentStatus.ACCEPTED,
        )
        db.add(assessment)
        await db.flush()
        db.add(
            GardenRevision(
                user_id=user.id,
                rev=1,
                rule_ver="rules@1+normal.1",
                assessment_ids=[assessment.id],
                reason="assessment",
                changes=[
                    {
                        "concept": w.bfs.key,
                        "status": {"before": "unassessed", "after": "sprouting"},
                        "scores": {
                            "before": None,
                            "after": {"explanation": {"independent": 0.6, "assisted": 0.6}},
                        },
                        "events": [
                            {
                                "assessment_id": str(assessment.id),
                                "evidence_ids": [str(evidence.id)],
                                "dimension": "explanation",
                            }
                        ],
                    }
                ],
            )
        )
        db.add(
            PlantState(
                user_id=user.id,
                concept_id=w.bfs.id,
                status=PlantStatus.SPROUTING,
                dimension_scores={"explanation": {"independent": 0.6, "assisted": 0.6}},
                last_evidence_at=NOW - timedelta(minutes=50),
                next_review_at=NOW + timedelta(days=4),
            )
        )
        private = Memory(
            user_id=user.id,
            layer=MemoryLayer.PRIVATE,
            kind="reflection",
            content="Anxious about conflict questions.",
            source=MemorySource.AGENT,
            source_character=Character.VIDURA,
            status=MemoryStatus.ACCEPTED,
        )
        profile = Memory(
            user_id=user.id,
            layer=MemoryLayer.PROFILE,
            kind="preference",
            content="Learns from examples.",
            source=MemorySource.USER,
            status=MemoryStatus.ACCEPTED,
            data={"concept_key": w.bfs.key},
        )
        db.add_all([private, profile])
        await db.flush()
        w.private_id, w.profile_id = private.id, profile.id
    return w


async def test_dataset_snapshot_and_analytics_from_the_database(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    w = await _world(maker)
    service = DbGardenService(maker)

    dataset = await service.dataset(w.clerk_id)
    assert dataset.readiness.target_role == "Backend engineer"
    assert str(w.evidence_id) in {e.id for e in dataset.evidence}
    event = dataset.growth_events[0]
    assert event.plant_key == w.bfs.key and event.evidence_ids == [str(w.evidence_id)]
    assert (event.from_stage, event.to_stage) == ("unassessed", "sprouting")
    assert dataset.sessions[0].minutes == 20
    assert {m.layer for m in dataset.memories} == {"private", "profile"}
    assert next(m for m in dataset.memories if m.layer == "profile").affects == [w.bfs.key]

    snapshot = await service.snapshot(w.clerk_id)
    plants = {p.concept_id: p for p in snapshot.plants}
    assert plants[w.bfs.key].status == "sprouting" and plants[w.bfs.key].evidence_count == 1
    assert snapshot.revision == 1 and snapshot.rule_version == "rules@1+normal.1"
    assert (w.graphs.key, w.bfs.key) in {(e.from_, e.to) for e in snapshot.prerequisites}
    before = await service.snapshot(w.clerk_id, rev=0)
    assert {p.status for p in before.plants} == {"unassessed"}

    practice = await service.analytics(w.clerk_id, "practice_time", make_query())
    assert practice.data["total_minutes"] >= 20
    detail = await service.analytics(w.clerk_id, "concept_detail", make_query(concept_id=w.bfs.key))
    assert detail.citations == [str(w.evidence_id)]

    assert (await service.revisions(w.clerk_id))[0].rev == 1


async def test_unknown_learner_sees_an_empty_garden(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    service = DbGardenService(maker)
    snapshot = await service.snapshot("clerk_nobody")
    assert snapshot.revision == 0
    assert (await service.dataset("clerk_nobody")).evidence == []
    assert await service.memories("clerk_nobody") == []
    ask = await service.ask("clerk_nobody", "How ready am I?")
    assert not ask.grounded


async def test_memory_correct_and_delete_are_scoped_and_append_only(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    w = await _world(maker)
    service = DbGardenService(maker)

    corrected = await service.correct_memory(w.clerk_id, w.profile_id, "Learns from diagrams.")
    assert corrected.text == "Learns from diagrams." and corrected.status == "accepted"
    assert corrected.id != str(w.profile_id)  # a new revision, not an in-place edit
    assert corrected.affects == [w.bfs.key]
    live = {m.id for m in await service.memories(w.clerk_id)}
    assert str(w.profile_id) not in live and corrected.id in live
    with pytest.raises(MemoryRuleViolation):  # the old revision is superseded
        await service.correct_memory(w.clerk_id, w.profile_id, "again")

    with pytest.raises(MemoryRuleViolation):  # only private reflections can be deleted
        await service.delete_memory(w.clerk_id, uuid.UUID(corrected.id))
    with pytest.raises(MemoryNotFound):  # another learner cannot touch it
        await service.delete_memory(w.other_clerk_id, w.private_id)
    await service.delete_memory(w.clerk_id, w.private_id)
    assert w.private_id not in {uuid.UUID(m.id) for m in await service.memories(w.clerk_id)}
    impact = await service.memory_impact(w.clerk_id, uuid.UUID(corrected.id))
    assert impact.affects == [w.bfs.key]


async def test_learner_analytics_continuous_aggregates_exist(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        rows = await db.execute(
            text(
                "SELECT view_name FROM timescaledb_information.continuous_aggregates "
                "WHERE view_schema = 'learner_analytics' ORDER BY 1"
            )
        )
        assert [r[0] for r in rows] == [
            "daily_event_mix",
            "daily_session_activity",
            "weekly_session_activity",
        ]
        # The loader's query shape works against the real view.
        await db.execute(
            text(
                "SELECT bucket, user_id, first_event_at, last_event_at "
                "FROM learner_analytics.daily_session_activity LIMIT 1"
            )
        )
