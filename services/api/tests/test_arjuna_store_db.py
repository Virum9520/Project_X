"""`DbArjunaStore` against a real database at DATABASE_URL (schema at head).

Opt-in with `SG_DB_TESTS=1`. The store opens its own sessions, so these tests create and delete
their own rows. The evidence test adds a throwaway active curriculum for its duration.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from sg_api.arjuna.problems import BY_ID
from sg_api.arjuna.runner import TestReport
from sg_api.arjuna.store import DbArjunaStore
from sg_api.drona.store import DbSessionStore, NewSession
from sg_core.db import get_engine, get_sessionmaker
from sg_core.models.curriculum import Concept, Curriculum
from sg_core.models.enums import CurriculumStatus, DocumentKind, DocumentVersionStatus
from sg_core.models.evidence import EvidenceItem
from sg_core.models.identity import User
from sg_core.models.knowledge import Chunk, Document, DocumentVersion
from sg_core.models.sessions import HintGiven, SandboxRun, SessionEvent

pytestmark = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)

PROBLEM = BY_ID["p_two_sum"]


@pytest.fixture(autouse=True)
async def _engine_for_this_loop() -> AsyncIterator[None]:
    """The store uses the process-wide engine; give each test's event loop its own."""
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()
    yield
    await get_engine().dispose()
    get_sessionmaker.cache_clear()
    get_engine.cache_clear()


@pytest.fixture
async def learner() -> tuple[str, uuid.UUID]:
    clerk = f"user_c16_{uuid.uuid4().hex[:10]}"
    async with get_sessionmaker()() as db:
        user = User(clerk_user_id=clerk, email=f"{clerk}@example.test")
        db.add(user)
        await db.commit()
        user_id = user.id
    yield clerk, user_id  # type: ignore[misc]
    async with get_sessionmaker()() as db:
        await db.execute(delete(User).where(User.clerk_user_id == clerk))
        await db.commit()


@pytest.fixture
async def curriculum(learner: tuple[str, uuid.UUID]) -> AsyncIterator[None]:
    """A throwaway active curriculum holding `dsa.hash_tables`, removed (after the learner's
    evidence, which restricts concept deletion) when the test ends."""
    async with get_sessionmaker()() as db:
        row = Curriculum(
            key=f"c16-test-{uuid.uuid4().hex[:8]}",
            version="v1",
            title="c16 test",
            status=CurriculumStatus.ACTIVE,
            content_hash="x",
        )
        db.add(row)
        await db.flush()
        db.add(Concept(curriculum_id=row.id, key=PROBLEM.concept_key, domain="dsa", title="Hash"))
        await db.commit()
        curriculum_id = row.id
    yield
    async with get_sessionmaker()() as db:
        await db.execute(delete(User).where(User.clerk_user_id == learner[0]))
        await db.execute(delete(Curriculum).where(Curriculum.id == curriculum_id))
        await db.commit()


async def _arjuna_session(clerk: str, character: str = "arjuna") -> uuid.UUID:
    sid = uuid.uuid4()
    mode = "technical_interview" if character == "arjuna" else "hr_interview"
    assert await DbSessionStore().create(
        NewSession(clerk, sid, character, mode, "agent_x", None, "dsa.hash_tables")
    )
    return sid


async def test_resolve_is_scoped_to_the_owner_and_the_character(
    learner: tuple[str, uuid.UUID],
) -> None:
    clerk, _ = learner
    store = DbArjunaStore()
    sid = await _arjuna_session(clerk)
    assert (await store.resolve(clerk, str(sid))) is not None
    assert await store.resolve("someone_else", str(sid)) is None
    assert await store.resolve(clerk, "not-a-uuid") is None
    drona = await _arjuna_session(clerk, character="drona")
    assert await store.resolve(clerk, str(drona)) is None


async def test_snapshots_dedupe_and_latest_wins(learner: tuple[str, uuid.UUID]) -> None:
    clerk, _ = learner
    store = DbArjunaStore()
    ctx = await store.resolve(clerk, str(await _arjuna_session(clerk)))
    assert ctx is not None
    first = await store.save_snapshot(
        ctx, problem_id=PROBLEM.id, language="python", code="a", trigger="autosave"
    )
    again = await store.save_snapshot(
        ctx, problem_id=PROBLEM.id, language="python", code="a", trigger="autosave"
    )
    assert not first.duplicate and again.duplicate and first.id == again.id
    await store.save_snapshot(
        ctx, problem_id=PROBLEM.id, language="python", code="b", trigger="autosave"
    )
    latest = await store.latest_snapshot(ctx, PROBLEM.id)
    assert latest is not None and latest.code == "b"
    assert await store.latest_snapshot(ctx, "p_other") is None


async def test_run_hint_and_evidence_round_trip(
    learner: tuple[str, uuid.UUID], curriculum: None
) -> None:
    clerk, user_id = learner
    store = DbArjunaStore()
    ctx = await store.resolve(clerk, str(await _arjuna_session(clerk)))
    assert ctx is not None
    await store.save_snapshot(
        ctx, problem_id=PROBLEM.id, language="python", code="x = 1", trigger="run"
    )
    snapshot = await store.latest_snapshot(ctx, PROBLEM.id)
    assert snapshot is not None

    assert await store.hint_levels(ctx, PROBLEM.id) == []
    await store.record_hint(ctx, PROBLEM, level=1, content=PROBLEM.hints[0])
    assert await store.hint_levels(ctx, PROBLEM.id) == [1]

    report = TestReport("failed", 5, 7, 900, "Passed 5 of 7 tests.")
    run = await store.record_run(
        ctx,
        problem=PROBLEM,
        snapshot=snapshot,
        report=report,
        kind="tests",
        assisted=True,
        now=datetime.now(UTC),
    )
    practice = await store.record_run(
        ctx,
        problem=PROBLEM,
        snapshot=snapshot,
        report=report,
        kind="examples",
        assisted=False,
        now=datetime.now(UTC),
    )
    assert await store.count_runs(ctx, "tests") == 1
    assert await store.count_runs(ctx, "examples") == 1
    listed = await store.list_runs(ctx, after=None, kind="tests")
    assert [r.id for r in listed] == [run.id] and listed[0].passed == 5 and listed[0].assisted

    async with get_sessionmaker()() as db:
        row = await db.get(SandboxRun, run.id)
        assert row is not None and row.code_snapshot_id == snapshot.id
        assert row.status.value == "failed" and row.tests_total == 7
        assert "payload" not in str(row.result)
        events = (
            await db.scalars(
                select(SessionEvent).where(
                    SessionEvent.session_id == ctx.session_id,
                    SessionEvent.event_type == "arjuna.tests_run",
                )
            )
        ).all()
        assert len(events) == 1  # practice runs emit nothing
        hints = (await db.scalars(select(HintGiven.id).where(HintGiven.user_id == user_id))).all()
        evidence = (
            await db.scalars(select(EvidenceItem).where(EvidenceItem.user_id == user_id))
        ).all()
        assert len(evidence) == 1  # only the graded run is evidence
        item = evidence[0]
        assert item.kind == "code_run" and item.assistance.value == "assisted"
        assert item.code_snapshot_id == snapshot.id and item.sandbox_run_id == run.id
        assert item.problem_family == "complement_lookup" and list(item.hint_ids) == list(hints)
        assert practice.id != run.id


async def test_plan_sources_read_the_active_resume_and_job_description(
    learner: tuple[str, uuid.UUID],
) -> None:
    clerk, user_id = learner
    async with get_sessionmaker()() as db:
        for kind, text in (
            (DocumentKind.RESUME, "Built a heap based scheduler"),
            (DocumentKind.JOB_DESCRIPTION, "We use BFS"),
            (DocumentKind.STUDY_MATERIAL, "Binary search notes"),
        ):
            doc = Document(user_id=user_id, kind=kind, title=kind.value)
            db.add(doc)
            await db.flush()
            version = DocumentVersion(
                document_id=doc.id,
                version=1,
                content_hash=uuid.uuid4().hex,
                storage_key=f"test/{uuid.uuid4().hex}",
                status=DocumentVersionStatus.ACTIVE,
            )
            db.add(version)
            await db.flush()
            doc.active_version_id = version.id
            db.add(
                Chunk(
                    document_version_id=version.id,
                    user_id=user_id,
                    ordinal=0,
                    content=text,
                    embedding=[0.0] * 1536,
                    embedding_model="test",
                )
            )
        await db.commit()
    sources = await DbArjunaStore().plan_sources(clerk)
    assert sources.resume_text == "Built a heap based scheduler"
    assert sources.job_description_text == "We use BFS"
    other = await DbArjunaStore().plan_sources("nobody_here")
    assert other.resume_text is None and other.job_description_text is None
