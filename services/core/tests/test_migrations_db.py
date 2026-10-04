"""Integration tests against a real TimescaleDB + pgvector database at DATABASE_URL.

Opt-in with `SG_DB_TESTS=1` (CI's `migrations` job sets it). They expect the schema to be at
`alembic upgrade head`, and every write is rolled back.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from sg_core.settings import get_settings

pytestmark = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)

ALEMBIC_INI = Path(__file__).parents[3] / "alembic.ini"


@pytest.fixture
async def conn() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(get_settings().database_url.unicode_string(), poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
    await engine.dispose()


async def _scalar(conn: AsyncConnection, sql: str, **params: object) -> object:
    return (await conn.execute(text(sql), params)).scalar_one()


async def _expect_integrity_error(conn: AsyncConnection, sql: str, **params: object) -> str:
    savepoint = await conn.begin_nested()
    with pytest.raises(IntegrityError) as excinfo:
        await conn.execute(text(sql), params)
    await savepoint.rollback()
    return str(excinfo.value.orig)


async def _user(conn: AsyncConnection, suffix: str = "a") -> object:
    return await _scalar(
        conn,
        "INSERT INTO users (clerk_user_id, email) VALUES (:c, :e) RETURNING id",
        c=f"user_test_{suffix}",
        e=f"{suffix}@example.test",
    )


def test_models_and_migrations_have_not_drifted() -> None:
    command.check(Config(str(ALEMBIC_INI)))


async def test_hypertables_exist(conn: AsyncConnection) -> None:
    rows = await conn.execute(
        text("SELECT hypertable_name FROM timescaledb_information.hypertables ORDER BY 1")
    )
    assert [r[0] for r in rows] == ["session_events", "usage_events"]


async def test_session_and_event_round_trip(conn: AsyncConnection) -> None:
    user_id = await _user(conn)
    session_id = await _scalar(
        conn,
        "INSERT INTO sessions (user_id, character, mode) VALUES (:u, 'drona', 'concept_exam') "
        "RETURNING id",
        u=user_id,
    )
    await conn.execute(
        text(
            "INSERT INTO session_events (session_id, user_id, event_type, source) "
            "VALUES (:s, :u, 'turn', 'agent')"
        ),
        {"s": session_id, "u": user_id},
    )
    assert (
        await _scalar(
            conn, "SELECT count(*) FROM session_events WHERE session_id = :s", s=session_id
        )
        == 1
    )


async def test_enum_check_constraints_reject_unknown_values(conn: AsyncConnection) -> None:
    user_id = await _user(conn)
    error = await _expect_integrity_error(
        conn,
        "INSERT INTO sessions (user_id, character, mode) VALUES (:u, 'gandalf', 'x')",
        u=user_id,
    )
    assert "ck_sessions_character" in error


async def test_provider_events_are_unique_per_provider_event_id(conn: AsyncConnection) -> None:
    insert = (
        "INSERT INTO provider_events (provider, event_id, event_type, signature_verified, payload) "
        "VALUES ('elevenlabs', 'evt_1', 'post_call_transcription', true, '{}')"
    )
    await conn.execute(text(insert))
    assert "uq_provider_events_provider_event" in await _expect_integrity_error(conn, insert)


async def test_usage_events_are_idempotent(conn: AsyncConnection) -> None:
    insert = (
        "INSERT INTO usage_events (occurred_at, idempotency_key, cost_center, component, "
        "provider, environment) VALUES ('2026-10-04T12:00:00Z', 'el:conv_1', 'learner', "
        "'drona_session', 'elevenlabs', 'test')"
    )
    await conn.execute(text(insert))
    assert "uq_usage_events_idempotency" in await _expect_integrity_error(conn, insert)


async def test_call_occurrence_is_unique_per_schedule_and_local_date(
    conn: AsyncConnection,
) -> None:
    user_id = await _user(conn)
    schedule_id = await _scalar(
        conn,
        "INSERT INTO call_schedules (user_id, channel, tz, local_time, days, consent_ver) "
        "VALUES (:u, 'web', 'America/Detroit', '07:30', '{1,3,5}', 'v1') RETURNING id",
        u=user_id,
    )
    insert = (
        "INSERT INTO call_occurrences (schedule_id, user_id, local_date, scheduled_for) "
        "VALUES (:s, :u, '2026-10-05', '2026-10-05T11:30:00Z')"
    )
    await conn.execute(text(insert), {"s": schedule_id, "u": user_id})
    error = await _expect_integrity_error(conn, insert, s=schedule_id, u=user_id)
    assert "uq_call_occurrences_schedule_local_date" in error


async def test_chunk_embeddings_support_cosine_search(conn: AsyncConnection) -> None:
    user_id = await _user(conn)
    document_id = await _scalar(
        conn,
        "INSERT INTO documents (user_id, kind, title) VALUES (:u, 'study_material', 'notes') "
        "RETURNING id",
        u=user_id,
    )
    version_id = await _scalar(
        conn,
        "INSERT INTO document_versions (document_id, version, content_hash, storage_key) "
        "VALUES (:d, 1, 'abc', 'docs/abc') RETURNING id",
        d=document_id,
    )
    await conn.execute(
        text("UPDATE documents SET active_version_id = :v WHERE id = :d"),
        {"v": version_id, "d": document_id},
    )
    for ordinal, hot in enumerate((0, 1)):
        vector = "[" + ",".join("1" if i == hot else "0" for i in range(1536)) + "]"
        await conn.execute(
            text(
                "INSERT INTO chunks (document_version_id, user_id, ordinal, content, embedding) "
                "VALUES (:v, :u, :o, :c, CAST(:e AS vector))"
            ),
            {"v": version_id, "u": user_id, "o": ordinal, "c": f"chunk {hot}", "e": vector},
        )
    query = "[" + ",".join("1" if i == 1 else "0" for i in range(1536)) + "]"
    nearest = await _scalar(
        conn,
        "SELECT content FROM chunks WHERE user_id = :u "
        "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 1",
        u=user_id,
        q=query,
    )
    assert nearest == "chunk 1"
