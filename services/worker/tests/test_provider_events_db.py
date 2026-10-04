"""Ingestion + processing against a real database (opt-in with SG_DB_TESTS=1).

Each test runs inside a transaction that is rolled back; session.commit() only releases a savepoint.
"""

import hashlib
import hmac
import json
import os
import time
import uuid
from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from sg_core.models.enums import ProviderEventStatus
from sg_core.models.sessions import ProviderEvent
from sg_core.settings import get_settings
from sg_core.webhooks import ElevenLabsVerifier, VerifierRegistry, ingest_webhook
from sg_worker.provider_events import (
    HandlerRegistry,
    ProcessOutcome,
    list_dead_letters,
    process_provider_event,
)

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
            yield AsyncSession(bind=connection, join_transaction_mode="create_savepoint")
        finally:
            await transaction.rollback()
    await engine.dispose()


class RecordingDispatcher:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[uuid.UUID] = []
        self.fail = fail

    async def dispatch(self, provider_event_id: uuid.UUID, provider: str, event_type: str) -> None:
        if self.fail:
            raise RuntimeError("queue down")
        self.calls.append(provider_event_id)


def _request(conversation_id: str) -> tuple[dict[str, str], bytes]:
    body = json.dumps(
        {"type": "post_call_transcription", "data": {"conversation_id": conversation_id}}
    ).encode()
    ts = int(time.time())
    mac = hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"ElevenLabs-Signature": f"t={ts},v0={mac}"}, body


def _registry() -> VerifierRegistry:
    registry = VerifierRegistry()
    registry.register(ElevenLabsVerifier(SecretStr(SECRET)))
    return registry


async def _ingest(session: AsyncSession, dispatcher: RecordingDispatcher, conv: str):
    headers, body = _request(conv)
    return await ingest_webhook(
        session, _registry(), dispatcher, provider="elevenlabs", headers=headers, body=body
    )


async def test_duplicate_delivery_stores_and_dispatches_once(session: AsyncSession) -> None:
    conv = f"conv_{uuid.uuid4().hex}"
    dispatcher = RecordingDispatcher()
    first = await _ingest(session, dispatcher, conv)
    second = await _ingest(session, dispatcher, conv)
    assert first.outcome == "accepted" and first.dispatched
    assert second.outcome == "duplicate" and not second.dispatched
    assert first.provider_event_id == second.provider_event_id
    assert dispatcher.calls == [first.provider_event_id]
    count = await session.scalar(
        select(func.count())
        .select_from(ProviderEvent)
        .where(ProviderEvent.event_id == f"post_call_transcription:{conv}")
    )
    assert count == 1
    row = await session.get(ProviderEvent, first.provider_event_id)
    assert row is not None and row.signature_verified
    assert row.status is ProviderEventStatus.ENQUEUED


async def test_dispatch_failure_keeps_event_and_retry_dispatches(session: AsyncSession) -> None:
    conv = f"conv_{uuid.uuid4().hex}"
    broken = await _ingest(session, RecordingDispatcher(fail=True), conv)
    assert not broken.dispatched
    row = await session.get(ProviderEvent, broken.provider_event_id)
    assert row is not None and row.status is ProviderEventStatus.RECEIVED
    healthy = RecordingDispatcher()
    retried = await _ingest(session, healthy, conv)
    assert retried.dispatched and healthy.calls == [broken.provider_event_id]


async def _stored(session: AsyncSession) -> uuid.UUID:
    result = await _ingest(session, RecordingDispatcher(), f"conv_{uuid.uuid4().hex}")
    return result.provider_event_id


async def test_handler_runs_once_then_is_skipped(session: AsyncSession) -> None:
    registry = HandlerRegistry()
    runs: list[uuid.UUID] = []

    @registry.register("elevenlabs", "post_call_transcription")
    async def handle(_s: AsyncSession, event: ProviderEvent) -> None:
        runs.append(event.id)

    event_id = await _stored(session)
    assert await process_provider_event(session, event_id, registry) is ProcessOutcome.PROCESSED
    assert await process_provider_event(session, event_id, registry) is ProcessOutcome.SKIPPED
    assert runs == [event_id]
    row = await session.get(ProviderEvent, event_id)
    assert row is not None and row.status is ProviderEventStatus.PROCESSED and row.processed_at


async def test_unregistered_event_type_is_ignored(session: AsyncSession) -> None:
    event_id = await _stored(session)
    outcome = await process_provider_event(session, event_id, HandlerRegistry())
    assert outcome is ProcessOutcome.IGNORED


async def test_failure_is_recorded_dead_lettered_and_retryable(session: AsyncSession) -> None:
    registry = HandlerRegistry()
    attempts = {"n": 0}

    @registry.register("elevenlabs", "post_call_transcription")
    async def flaky(_s: AsyncSession, _e: ProviderEvent) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ValueError("boom")

    event_id = await _stored(session)
    with pytest.raises(ValueError):
        await process_provider_event(session, event_id, registry)
    row = await session.get(ProviderEvent, event_id)
    assert row is not None and row.status is ProviderEventStatus.FAILED
    assert row.error is not None and "boom" in row.error and row.attempts == 1
    assert event_id in [e.id for e in await list_dead_letters(session)]

    assert await process_provider_event(session, event_id, registry) is ProcessOutcome.PROCESSED
    await session.refresh(row)
    assert row.status is ProviderEventStatus.PROCESSED and row.error is None and row.attempts == 2
