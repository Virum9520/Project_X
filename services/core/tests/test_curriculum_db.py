"""`sync_curriculum` against a real database at DATABASE_URL (schema at `alembic upgrade head`).

Opt-in with `SG_DB_TESTS=1`. Every write happens in a transaction that is rolled back.
"""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from sg_core.curriculum import CurriculumError, curriculum_path, load_curriculum, sync_curriculum
from sg_core.curriculum.schema import CurriculumSpec
from sg_core.models.curriculum import Concept, ConceptEdge, Curriculum, Rubric
from sg_core.models.enums import ConceptEdgeKind, CurriculumStatus
from sg_core.settings import get_settings

pytestmark = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)

# A key no real curriculum uses, so tests never collide with a loaded `cs-core`.
TEST_KEY = "cs-core-test"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url.unicode_string(), poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
        finally:
            await transaction.rollback()
    await engine.dispose()


def _spec(version: str = "v1", title: str | None = None) -> CurriculumSpec:
    spec = load_curriculum(curriculum_path("cs-core", "v1"))
    return spec.model_copy(
        update={"key": TEST_KEY, "version": version, "title": title or spec.title}
    )


async def _count(session: AsyncSession, model: type, curriculum_id: object) -> int:
    if model is ConceptEdge:
        query = (
            select(func.count())
            .select_from(ConceptEdge)
            .join(Concept, Concept.id == ConceptEdge.to_concept_id)
            .where(Concept.curriculum_id == curriculum_id)
        )
    else:
        query = select(func.count()).where(model.curriculum_id == curriculum_id)  # type: ignore[attr-defined]
    return int(await session.scalar(query) or 0)


async def test_sync_creates_then_is_idempotent(session: AsyncSession) -> None:
    spec = _spec()
    created = await sync_curriculum(session, spec)
    assert created.action == "created"
    assert created.status is CurriculumStatus.DRAFT
    assert await _count(session, Concept, created.curriculum_id) == len(spec.concepts)
    assert await _count(session, ConceptEdge, created.curriculum_id) == created.edges
    assert await _count(session, Rubric, created.curriculum_id) == created.rubrics

    again = await sync_curriculum(session, spec)
    assert again.action == "unchanged"
    assert again.curriculum_id == created.curriculum_id
    assert await _count(session, Concept, created.curriculum_id) == len(spec.concepts)

    edge_kind = await session.scalar(
        select(ConceptEdge.kind)
        .join(Concept, Concept.id == ConceptEdge.from_concept_id)
        .where(Concept.curriculum_id == created.curriculum_id, Concept.key == "dsa.arrays")
        .limit(1)
    )
    assert edge_kind is ConceptEdgeKind.PREREQUISITE
    rubric = await session.scalar(
        select(Rubric).where(Rubric.key == f"{TEST_KEY}@v1/dsa.hash_tables")
    )
    assert rubric is not None and rubric.concept_id is not None and rubric.version == 1


async def test_changed_draft_is_replaced_but_active_is_immutable(session: AsyncSession) -> None:
    first = await sync_curriculum(session, _spec())
    replaced = await sync_curriculum(session, _spec(title="Renamed"))
    assert replaced.action == "replaced"
    assert replaced.curriculum_id == first.curriculum_id
    assert await _count(session, Concept, first.curriculum_id) == first.concepts

    activated = await sync_curriculum(session, _spec(title="Renamed"), activate=True)
    assert activated.status is CurriculumStatus.ACTIVE
    with pytest.raises(CurriculumError, match="immutable"):
        await sync_curriculum(session, _spec(title="Changed again"))


async def test_activation_retires_the_previous_version(session: AsyncSession) -> None:
    v1 = await sync_curriculum(session, _spec("v1"), activate=True)
    v2 = await sync_curriculum(session, _spec("v2"), activate=True)
    statuses = dict(
        (
            await session.execute(
                select(Curriculum.version, Curriculum.status).where(Curriculum.key == TEST_KEY)
            )
        ).all()
    )
    assert statuses == {"v1": CurriculumStatus.RETIRED, "v2": CurriculumStatus.ACTIVE}
    assert v1.curriculum_id != v2.curriculum_id
