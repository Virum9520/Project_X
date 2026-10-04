"""Webhook -> stored event -> handler -> garden, against a real database (SG_DB_TESTS=1).

Each test runs inside a rolled-back transaction; `session.commit()` only releases a savepoint.
"""

import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core" / "tests"))

from evidence_fixtures import CONV, T0, ScriptedLLM, judge_body, payload, verdict

from sg_core.curriculum import curriculum_path, load_curriculum, sync_curriculum
from sg_core.evidence import LLMJudge, PipelineDeps
from sg_core.evidence.db_store import DbEvidenceStore
from sg_core.models.curriculum import Curriculum
from sg_core.models.enums import Character, CurriculumStatus, ProviderEventStatus
from sg_core.models.evidence import Assessment, GardenRevision
from sg_core.models.identity import User
from sg_core.rules import load_profile
from sg_core.settings import get_settings
from sg_core.webhooks import ElevenLabsVerifier, VerifierRegistry, ingest_webhook
from sg_worker import post_call
from sg_worker.provider_events import handlers, process_provider_event

pytestmark = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)

SECRET = "whsec_test"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url.unicode_string(), poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            s = AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
            active = await s.scalar(
                select(Curriculum.id).where(Curriculum.status == CurriculumStatus.ACTIVE)
            )
            if active is None:
                await sync_curriculum(
                    s, load_curriculum(curriculum_path("cs-core", "v1")), activate=True
                )
                await s.flush()
            yield s
        finally:
            await transaction.rollback()
    await engine.dispose()


class NoDispatch:
    async def dispatch(self, provider_event_id: uuid.UUID, provider: str, event_type: str) -> None:
        return None


async def _webhook(session: AsyncSession, data: dict) -> uuid.UUID:  # type: ignore[type-arg]
    body = json.dumps({"type": "post_call_transcription", "data": data}).encode()
    ts = int(time.time())
    mac = hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    registry = VerifierRegistry()
    registry.register(ElevenLabsVerifier(SecretStr(SECRET)))
    result = await ingest_webhook(
        session,
        registry,
        NoDispatch(),
        provider="elevenlabs",
        headers={"ElevenLabs-Signature": f"t={ts},v0={mac}"},
        body=body,
    )
    return result.provider_event_id


def _install(monkeypatch: pytest.MonkeyPatch, llm: ScriptedLLM) -> None:
    @asynccontextmanager
    async def factory(s: AsyncSession) -> AsyncIterator[PipelineDeps]:
        yield PipelineDeps(
            store=DbEvidenceStore(s),
            judge=LLMJudge(llm, "judge-model"),
            profile_for=lambda demo: load_profile("normal"),
            clock=lambda: T0,
        )

    monkeypatch.setattr(post_call, "runtime_factory", factory)


async def _learner(session: AsyncSession) -> User:
    user = User(clerk_user_id=f"c_{uuid.uuid4().hex}", email=f"{uuid.uuid4().hex}@t.dev")
    session.add(user)
    await session.flush()
    await DbEvidenceStore(session).ensure_session(
        user_id=user.id,
        character=Character.DRONA,
        mode="concept_exam",
        conversation_id=CONV,
        public_session_id="ses_1",
        now=T0,
    )
    return user


async def test_webhook_to_garden_through_the_registered_handler(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = (await _learner(session)).id
    _install(monkeypatch, ScriptedLLM(judge_body(verdict(family="h"))))
    event_id = await _webhook(session, payload())

    outcome = await process_provider_event(session, event_id, handlers)
    assert outcome.value == "processed"
    revisions = await session.scalar(
        select(func.count()).select_from(GardenRevision).where(GardenRevision.user_id == uid)
    )
    assert revisions == 1
    # A duplicate delivery is a no-op: the event is terminal and nothing is awarded twice.
    again = await process_provider_event(session, event_id, handlers)
    assert again.value == "skipped"
    assert await session.scalar(select(func.count()).select_from(Assessment)) == 1


async def test_a_failing_judge_rolls_back_everything_and_a_retry_succeeds(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sg_core.evidence import JudgeError

    uid = (await _learner(session)).id
    _install(monkeypatch, ScriptedLLM("this is not json"))
    event_id = await _webhook(session, payload())
    with pytest.raises(JudgeError):
        await process_provider_event(session, event_id, handlers)
    from sg_core.models.sessions import ProviderEvent

    row = await session.get(ProviderEvent, event_id)
    assert row is not None and row.status is ProviderEventStatus.FAILED and row.attempts == 1
    assert await session.scalar(select(func.count()).select_from(Assessment)) == 0

    _install(monkeypatch, ScriptedLLM(judge_body(verdict(family="h"))))
    assert (await process_provider_event(session, event_id, handlers)).value == "processed"
    assert (
        await session.scalar(
            select(func.count()).select_from(GardenRevision).where(GardenRevision.user_id == uid)
        )
        == 1
    )
