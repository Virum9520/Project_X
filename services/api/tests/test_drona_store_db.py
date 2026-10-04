"""`DbSessionStore` and `DbGrowthFeed` against a real database at DATABASE_URL (schema at head).

Opt-in with `SG_DB_TESTS=1`. The stores open their own sessions through `get_sessionmaker`, so
these tests create and delete their own rows instead of relying on a rollback.
"""

import os
import uuid

import pytest
from sqlalchemy import delete

from sg_api.drona.growth import DbGrowthFeed, GrowthEvent
from sg_api.drona.store import DbSessionStore, NewSession
from sg_core.db import get_sessionmaker
from sg_core.models.enums import SessionStatus
from sg_core.models.identity import User
from sg_core.models.sessions import Session as SessionRow

pytestmark = pytest.mark.skipif(
    not os.getenv("SG_DB_TESTS"), reason="set SG_DB_TESTS=1 to run database tests"
)


@pytest.fixture
async def clerk_id() -> str:
    clerk = f"user_c12_{uuid.uuid4().hex[:10]}"
    async with get_sessionmaker()() as db:
        db.add(User(clerk_user_id=clerk, email=f"{clerk}@example.test"))
        await db.commit()
    yield clerk  # type: ignore[misc]
    async with get_sessionmaker()() as db:
        await db.execute(delete(User).where(User.clerk_user_id == clerk))
        await db.commit()


async def test_session_row_lifecycle(clerk_id: str) -> None:
    store = DbSessionStore()
    sid = uuid.uuid4()
    stored = await store.create(
        NewSession(clerk_id, sid, "panel", "panel_interview", "agent_x", None, "dsa.bfs")
    )
    assert stored is True
    async with get_sessionmaker()() as db:
        row = await db.get(SessionRow, sid)
        assert row is not None
        assert row.character.value == "vidura"  # panel sessions are stored as Vidura
        assert row.attributes["focus_concept"] == "dsa.bfs"
    assert await store.session_focus(clerk_id, str(sid)) == "dsa.bfs"
    assert await store.bind_conversation(clerk_id, str(sid), "conv_a") == "bound"
    assert await store.bind_conversation(clerk_id, str(sid), "conv_a") == "same"
    assert await store.bind_conversation(clerk_id, str(sid), "conv_b") == "conflict"
    assert await store.end(clerk_id, str(sid), SessionStatus.COMPLETED) is True
    assert await store.end("someone_else", str(sid), SessionStatus.COMPLETED) is False


async def test_unknown_learner_is_not_stored() -> None:
    new = NewSession("user_nobody", uuid.uuid4(), "drona", "concept_exam", "a", None, None)
    assert await DbSessionStore().create(new) is False


async def test_growth_feed_round_trips_through_session_events(clerk_id: str) -> None:
    store, feed = DbSessionStore(), DbGrowthFeed()
    sid = uuid.uuid4()
    await store.create(NewSession(clerk_id, sid, "drona", "concept_exam", "a", None, None))
    cursor = await feed.latest_cursor(clerk_id)
    event = GrowthEvent(
        kind="provisional",
        session_id=str(sid),
        concept_id="dsa.bfs",
        dimension="explanation",
        part="roots",
        outcome="demonstrated",
    )
    await feed.append(clerk_id, event)
    (got,) = await feed.after(clerk_id, cursor)
    assert got[1].concept_id == "dsa.bfs"
    assert got[1].part == "roots"
