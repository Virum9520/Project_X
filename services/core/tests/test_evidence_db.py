"""Evidence pipeline against a real database (opt-in with SG_DB_TESTS=1).

Every test runs in a transaction that is rolled back. Uses the active curriculum if one is
loaded, otherwise loads `cs-core@v1` inside the test transaction.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from evidence_fixtures import (
    BS,
    CONV,
    START,
    T0,
    ScriptedLLM,
    judge_body,
    observation_call,
    payload,
    turn,
    verdict,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from sg_core.curriculum import curriculum_path, load_curriculum, sync_curriculum
from sg_core.evidence import (
    LLMJudge,
    MicroJudge,
    ObservationInput,
    PipelineDeps,
    StaleGardenError,
    record_observation,
    run_post_call,
)
from sg_core.evidence.db_store import DbEvidenceStore
from sg_core.memory import garden_view, growth_events, uncited_growth
from sg_core.models.accountability import CallAttempt, CallOccurrence
from sg_core.models.curriculum import Curriculum
from sg_core.models.enums import (
    AssessmentStatus,
    CallChannelKind,
    Character,
    CurriculumStatus,
    MemoryLayer,
    MemoryStatus,
    PlantStatus,
)
from sg_core.models.evidence import Assessment, EvidenceItem, GardenRevision, PlantState
from sg_core.models.identity import User
from sg_core.models.memory import Memory
from sg_core.models.sessions import HintGiven, SessionEvent
from sg_core.rules import load_profile
from sg_core.settings import get_settings

pytestmark = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)

NOW = T0 + timedelta(minutes=5)


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url.unicode_string(), poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
            active = await session.scalar(
                select(Curriculum.id).where(Curriculum.status == CurriculumStatus.ACTIVE)
            )
            if active is None:
                spec = load_curriculum(curriculum_path("cs-core", "v1"))
                await sync_curriculum(session, spec, activate=True)
                await session.flush()
            yield session
        finally:
            await transaction.rollback()
    await engine.dispose()


async def new_user(db: AsyncSession) -> User:
    user = User(clerk_user_id=f"clerk_{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
    db.add(user)
    await db.flush()
    return user


def deps(store: DbEvidenceStore, llm: ScriptedLLM) -> PipelineDeps:
    return PipelineDeps(
        store=store,
        judge=LLMJudge(llm, "judge-model"),
        profile_for=lambda demo: load_profile("demo" if demo else "normal"),
        clock=lambda: NOW,
    )


async def start(store: DbEvidenceStore, user: User, conv: str = CONV) -> uuid.UUID:
    ref = await store.ensure_session(
        user_id=user.id,
        character=Character.DRONA,
        mode="concept_exam",
        conversation_id=conv,
        public_session_id="ses_x",
        now=T0,
    )
    return ref.id


async def test_post_call_writes_a_cited_garden_revision(db: AsyncSession) -> None:
    user = await new_user(db)
    store = DbEvidenceStore(db)
    sid = await start(store, user)
    mem = await record_observation(
        store,
        MicroJudge(
            ScriptedLLM({"outcome": "demonstrated", "uncertainty": 0.1, "rationale": "r"}), "t"
        ),
        session=(await store.find_session(CONV)),  # type: ignore[arg-type]
        obs=ObservationInput(BS, "explanation", "correct", "independent", "it halves the range"),
        now=T0,
    )
    assert mem.glow

    result = await run_post_call(
        deps(store, ScriptedLLM(judge_body(verdict(family="halving")))), payload()
    )
    assert result.revision == 1 and result.confirmed == 1

    assessment = (await db.scalars(select(Assessment).where(Assessment.session_id == sid))).one()
    assert assessment.status is AssessmentStatus.ACCEPTED and assessment.rubric_ver
    evidence = (
        await db.scalars(select(EvidenceItem).where(EvidenceItem.id.in_(assessment.evidence_ids)))
    ).all()
    assert [e.quote for e in evidence] == ["it halves the search range each step"]

    revision = (
        await db.scalars(select(GardenRevision).where(GardenRevision.user_id == user.id))
    ).one()
    assert revision.rule_ver.startswith("rules@") and assessment.id in revision.assessment_ids
    plant = (await db.scalars(select(PlantState).where(PlantState.user_id == user.id))).one()
    assert plant.status is PlantStatus.SPROUTING and plant.garden_revision_id == revision.id

    # The C09/C14 projections read this revision and find every growth event cited.
    view = await garden_view(db, user.id)
    assert next(p for p in view.plants if p.key == BS).status == "sprouting"
    assert await uncited_growth(db, user.id) == []
    events = await growth_events(db, user.id)
    assert events and all(e.cited for e in events)
    old = await garden_view(db, user.id, rev=1)
    assert next(p for p in old.plants if p.key == BS).status == "sprouting"

    memories = (await db.scalars(select(Memory).where(Memory.user_id == user.id))).all()
    promoted = [
        m for m in memories if m.kind == "provisional_growth" and m.status is MemoryStatus.ACCEPTED
    ]
    assert len(promoted) == 1 and promoted[0].evidence_ids
    assert any(
        m.layer is MemoryLayer.SKILLS and m.kind == "demonstrated_explanation" for m in memories
    )
    types = set(
        await db.scalars(select(SessionEvent.event_type).where(SessionEvent.session_id == sid))
    )
    assert {"garden.provisional_growth", "garden.revision", "garden.provisional_confirmed"} <= types


async def test_replay_and_duplicate_dedupe_keys_do_not_duplicate_rows(db: AsyncSession) -> None:
    user = await new_user(db)
    store = DbEvidenceStore(db)
    sid = await start(store, user)
    d = deps(store, ScriptedLLM(judge_body(verdict(family="halving"))))
    await run_post_call(d, payload())
    again = await run_post_call(d, payload())
    assert again.status == "unchanged"
    for model in (Assessment, GardenRevision, EvidenceItem):
        count = await db.scalar(
            select(func.count()).select_from(model).where(model.user_id == user.id)
        )
        assert count == 1, model
    assert sid


async def test_assisted_and_independent_stay_separate_in_the_plant_row(db: AsyncSession) -> None:
    user = await new_user(db)
    store = DbEvidenceStore(db)
    sid = await start(store, user)
    db.add(HintGiven(session_id=sid, user_id=user.id, level=1, content="think about the middle"))
    await db.flush()
    await run_post_call(deps(store, ScriptedLLM(judge_body(verdict(family="h")))), payload())
    plant = (await db.scalars(select(PlantState).where(PlantState.user_id == user.id))).one()
    scores = plant.dimension_scores["explanation"]
    assert plant.status is PlantStatus.ASSISTED
    assert scores["independent"] == 0.0 and scores["assisted"] == 1.0


async def test_stale_revision_is_refused(db: AsyncSession) -> None:
    user = await new_user(db)
    store = DbEvidenceStore(db)
    await start(store, user)
    await run_post_call(deps(store, ScriptedLLM(judge_body(verdict(family="h")))), payload())
    snap = await store.garden_state(user.id)
    assert snap.rev == 1 and snap.state.applied
    from sg_core.rules import propose

    empty = propose(snap.state, [], NOW, load_profile("normal"))
    with pytest.raises(StaleGardenError):
        await store.commit_garden(
            user.id, expected_rev=0, result=empty, reason="assessment", now=NOW
        )


async def test_rejudging_and_out_of_order_rebuild_from_stored_assessments(db: AsyncSession) -> None:
    user = await new_user(db)
    store = DbEvidenceStore(db)
    await start(store, user)
    await run_post_call(deps(store, ScriptedLLM(judge_body(verdict(family="h")))), payload())
    longer = [*payload()["transcript"], turn("user", "Actually I am not sure.", 60)]
    result = await run_post_call(
        deps(store, ScriptedLLM(judge_body(verdict(outcome="not_demonstrated")))), payload(longer)
    )
    assert result.revision == 2
    revisions = (
        await db.scalars(
            select(GardenRevision)
            .where(GardenRevision.user_id == user.id)
            .order_by(GardenRevision.rev)
        )
    ).all()
    assert [r.reason for r in revisions] == ["assessment", "correction"]
    statuses = sorted(
        s.value
        for s in await db.scalars(select(Assessment.status).where(Assessment.user_id == user.id))
    )
    assert statuses == ["accepted", "superseded"]
    plant = (await db.scalars(select(PlantState).where(PlantState.user_id == user.id))).one()
    assert plant.status is PlantStatus.UNASSESSED


async def test_bhima_call_gets_a_session_and_retention_is_judged(db: AsyncSession) -> None:
    user = await new_user(db)
    store = DbEvidenceStore(db)
    # An earlier independent explanation, two days ago, through the normal pipeline.
    await start(store, user, "conv_learn")
    old = payload(conversation_id="conv_learn")
    old["metadata"]["start_time_unix_secs"] = START - 2 * 86400
    await run_post_call(deps(store, ScriptedLLM(judge_body(verdict(family="h")))), old)

    occurrence = CallOccurrence(
        user_id=user.id, local_date=date(2026, 10, 4), scheduled_for=T0, is_test=False
    )
    db.add(occurrence)
    await db.flush()
    attempt = CallAttempt(
        occurrence_id=occurrence.id,
        attempt_no=1,
        channel=CallChannelKind.WEB,
        el_conversation_id="conv_bhima",
    )
    db.add(attempt)
    await db.flush()
    from sg_core.memory import MemoryStore, NewMemory
    from sg_core.models.enums import MemorySource

    await MemoryStore(db).append(
        NewMemory(
            user_id=user.id,
            layer=MemoryLayer.SESSION,
            kind="retention_check",
            content="Bhima asked a retention question.",
            source=MemorySource.SYSTEM,
            status=MemoryStatus.ACCEPTED,
            data={"concept_key": BS, "attempt_id": str(attempt.id), "source": "retention_call"},
        )
    )
    turns = [
        turn("agent", "What makes binary search logarithmic?", 100),
        turn("user", "Each comparison halves what is left, so log n steps.", 110),
    ]
    llm = ScriptedLLM(
        judge_body(
            verdict(dimension="retention", turn=1, quote="Each comparison halves what is left")
        )
    )
    result = await run_post_call(
        deps(store, llm), payload(turns, conversation_id="conv_bhima", focus=None)
    )
    assert result.revision == 2
    ref = await store.find_session("conv_bhima")
    assert ref is not None and ref.character == "bhima" and ref.user_id == user.id
    plant = (await db.scalars(select(PlantState).where(PlantState.user_id == user.id))).one()
    assert plant.status is PlantStatus.RETAINED
    refreshed = await db.get(CallAttempt, attempt.id)
    assert refreshed is not None and refreshed.session_id == ref.id


async def test_call_now_test_calls_have_no_learner_and_no_session(db: AsyncSession) -> None:
    store = DbEvidenceStore(db)
    occurrence = CallOccurrence(
        user_id=None, local_date=date(2026, 10, 4), scheduled_for=T0, is_test=True
    )
    db.add(occurrence)
    await db.flush()
    db.add(
        CallAttempt(
            occurrence_id=occurrence.id,
            attempt_no=1,
            channel=CallChannelKind.WEB,
            el_conversation_id="conv_test",
        )
    )
    await db.flush()
    assert await store.find_session("conv_test") is None


async def test_unknown_conversation_has_no_session(db: AsyncSession) -> None:
    assert await DbEvidenceStore(db).find_session("conv_nobody") is None


async def test_other_learners_data_is_untouched(db: AsyncSession) -> None:
    mine, theirs = await new_user(db), await new_user(db)
    store = DbEvidenceStore(db)
    await start(store, mine)
    await start(store, theirs, "conv_theirs")
    await run_post_call(deps(store, ScriptedLLM(judge_body(verdict(family="h")))), payload())
    assert (await store.garden_state(theirs.id)).rev == 0
    assert (await store.garden_state(mine.id)).rev == 1
    assert observation_call() and datetime.now(UTC)
