"""DbConsentStore against a real database (schema at `alembic upgrade head`).

Opt-in with `SG_DB_TESTS=1`. Every write is rolled back.
"""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from sg_core.models.identity import User
from sg_core.settings import get_settings
from sg_core.voice_clone import ConsentRecord, DbConsentStore

pytestmark = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)

Sessions = async_sessionmaker[AsyncSession]


@pytest.fixture
async def sessions() -> AsyncIterator[Sessions]:
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


async def test_consent_lifecycle(sessions: Sessions) -> None:
    user_id = uuid.uuid4()
    async with sessions() as session, session.begin():
        session.add(
            User(id=user_id, clerk_user_id=f"user_{user_id.hex}", email=f"{user_id}@e.test")
        )
    store = DbConsentStore(sessions)
    record_id = uuid.uuid4()
    await store.add(
        ConsentRecord(
            id=record_id,
            user_id=user_id,
            consent_ver="future-self-v1",
            recording_s3="voice-consents/x.webm",
            phrase_verified=True,
            verified_transcript="hello",
            voice_id=None,
            created_at=datetime.now(UTC),
        )
    )
    assert (await store.get_current(user_id)) is not None
    record = await store.set_voice(record_id, "voice_1")
    assert record.active
    revoked = await store.revoke(record_id, at=datetime.now(UTC))
    assert revoked.voice_id is None and revoked.recording_s3 == ""
    assert revoked.verified_transcript is None and revoked.revoked_at is not None
    assert await store.get_current(user_id) is None
    assert len(await store.history(user_id)) == 1
    await store.delete(record_id)
    assert await store.history(user_id) == []
