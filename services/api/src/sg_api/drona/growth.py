"""Live provisional growth: the micro-judge seam and the event feed behind the SSE channel.

Flow during a call: Drona calls `record_observation` (`sg_api.agent_tools.record_observation`,
C11), whose micro-judge writes `garden.provisional_*` session events; `GET /v1/live/growth`
translates them (`growth_event_from_c11`) and streams them to every open tab of that learner,
where they become `pulseConceptIds` on the garden scene and rows in the evidence ticker.

Integrity: nothing here changes the garden. A provisional event is a glow, stored as a
`session_events` row; only the post-call pipeline (C11) creates assessments and revisions, and it
announces the outcome with `confirmed` or `retracted` events through the same feed.

Cross-process: the API and the Hatchet worker are different processes, so the durable feed is the
`session_events` table (event types `growth.provisional|confirmed|retracted|noted`). C11 only
has to insert such a row, with a `GrowthEvent` dict as payload, and open streams pick it up.
"""

import asyncio
import json
import time
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import or_, select

from sg_core.db import get_sessionmaker
from sg_core.logging import get_logger
from sg_core.models.enums import EventSource
from sg_core.models.identity import User
from sg_core.models.sessions import Session as SessionRow
from sg_core.models.sessions import SessionEvent

log = get_logger(__name__)

GrowthKind = Literal["provisional", "confirmed", "retracted", "noted"]
Outcome = Literal["demonstrated", "partial", "not_demonstrated", "unassessable"]
EVENT_PREFIX = "growth."
# C11 writes these `session_events` rows from the tool route and the post-call pipeline.
C11_KINDS: dict[str, GrowthKind] = {
    "garden.provisional_growth": "provisional",
    "garden.provisional_confirmed": "confirmed",
    "garden.provisional_retracted": "retracted",
}
DIMENSION_PART = {
    "explanation": "roots",
    "application": "stem",
    "transfer": "branches",
    "retention": "blossoms",
}
MAX_QUOTE_WORDS = 60

AgentOutcome = Literal["correct", "partially_correct", "incorrect", "no_attempt"]
AgentAssistance = Literal["independent", "hinted", "heavily_assisted"]


class GrowthEvent(BaseModel):
    """What the browser receives. camelCase on the wire, like the garden API."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    kind: GrowthKind
    session_id: str
    concept_id: str  # concept key, e.g. dsa.binary_search
    question_id: str | None = None
    dimension: str
    part: str | None = None  # roots | stem | branches | blossoms; None when nothing grows
    outcome: Outcome
    assisted: bool = False
    quote: str = ""
    note: str = ""
    judge: str = ""
    reason: str = ""  # retraction explanation shown to the learner
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# --------------------------------------------------------------------------------- the feed


class GrowthFeed(Protocol):
    """Per-learner event log. `user_ref` is the Clerk user ID (the identity in tool tokens).
    A cursor is an opaque string; `after(None)` is not allowed, use `latest_cursor`."""

    async def append(self, user_ref: str, event: GrowthEvent) -> None: ...

    async def after(
        self, user_ref: str, cursor: str, limit: int = 50
    ) -> list[tuple[str, GrowthEvent]]: ...

    async def latest_cursor(self, user_ref: str) -> str: ...


def _micros(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000_000)


class MemoryGrowthFeed:
    """Process-local feed: tests, and local runs without a database."""

    def __init__(self) -> None:
        self._events: dict[str, list[tuple[int, GrowthEvent]]] = defaultdict(list)
        self._last = 0

    def _stamp(self, moment: datetime) -> int:
        self._last = max(self._last + 1, _micros(moment))
        return self._last

    async def append(self, user_ref: str, event: GrowthEvent) -> None:
        self._events[user_ref].append((self._stamp(event.occurred_at), event))
        del self._events[user_ref][:-500]

    async def after(
        self, user_ref: str, cursor: str, limit: int = 50
    ) -> list[tuple[str, GrowthEvent]]:
        floor = int(cursor)
        return [(str(t), e) for t, e in self._events[user_ref] if t > floor][:limit]

    async def latest_cursor(self, user_ref: str) -> str:
        return str(max(_micros(datetime.now(UTC)), self._last))


class DbGrowthFeed:
    """`session_events` rows, with a process-local fallback for sessions that were never stored
    (a learner with no `users` row yet)."""

    def __init__(self, fallback: MemoryGrowthFeed | None = None) -> None:
        self._fallback = fallback or MemoryGrowthFeed()

    async def append(self, user_ref: str, event: GrowthEvent) -> None:
        try:
            async with get_sessionmaker()() as db:
                user_id = await db.scalar(
                    select(User.id).where(User.clerk_user_id == user_ref, User.deleted_at.is_(None))
                )
                session_id = _uuid(event.session_id)
                owned = (
                    session_id is not None
                    and user_id is not None
                    and await db.scalar(
                        select(SessionRow.id).where(
                            SessionRow.id == session_id, SessionRow.user_id == user_id
                        )
                    )
                )
                if owned and user_id is not None and session_id is not None:
                    db.add(
                        SessionEvent(
                            occurred_at=event.occurred_at,
                            session_id=session_id,
                            user_id=user_id,
                            event_type=EVENT_PREFIX + event.kind,
                            source=EventSource.SERVER,
                            payload=event.model_dump(mode="json", by_alias=True),
                        )
                    )
                    await db.commit()
                    return
        except Exception:
            log.warning("growth.append_failed", exc_info=True)
        await self._fallback.append(user_ref, event)

    async def after(
        self, user_ref: str, cursor: str, limit: int = 50
    ) -> list[tuple[str, GrowthEvent]]:
        rows: list[tuple[str, GrowthEvent]] = []
        try:
            floor = datetime.fromtimestamp(int(cursor) / 1_000_000, UTC)
            async with get_sessionmaker()() as db:
                found = (
                    await db.execute(
                        select(
                            SessionEvent.occurred_at,
                            SessionEvent.event_type,
                            SessionEvent.session_id,
                            SessionEvent.payload,
                        )
                        .join(User, User.id == SessionEvent.user_id)
                        .where(
                            User.clerk_user_id == user_ref,
                            or_(
                                SessionEvent.event_type.like(EVENT_PREFIX + "%"),
                                SessionEvent.event_type.in_(list(C11_KINDS)),
                            ),
                            SessionEvent.occurred_at > floor,
                        )
                        .order_by(SessionEvent.occurred_at)
                        .limit(limit)
                    )
                ).all()
            for at, event_type, sid, payload in found:
                if event_type.startswith(EVENT_PREFIX):
                    parsed: GrowthEvent | None = GrowthEvent.model_validate(payload)
                else:
                    parsed = growth_event_from_c11(event_type, sid, at, dict(payload or {}))
                if parsed is not None:
                    rows.append((str(_micros(at)), parsed))
        except Exception:
            log.warning("growth.read_failed", exc_info=True)
        rows += await self._fallback.after(user_ref, cursor, limit)
        rows.sort(key=lambda r: int(r[0]))
        return rows[:limit]

    async def latest_cursor(self, user_ref: str) -> str:
        return await self._fallback.latest_cursor(user_ref)


def growth_event_from_c11(
    event_type: str, session_id: uuid.UUID, occurred_at: datetime, payload: dict[str, object]
) -> GrowthEvent | None:
    """Translate a C11 evidence-pipeline event into the browser's `GrowthEvent`."""
    kind = C11_KINDS.get(event_type)
    concept = payload.get("concept")
    if kind is None or not isinstance(concept, str):
        return None
    dimension = str(payload.get("dimension") or "")
    outcome = str(payload.get("outcome") or "demonstrated")
    return GrowthEvent(
        id=uuid.uuid5(
            session_id, f"{event_type}:{concept}:{dimension}:{occurred_at.isoformat()}"
        ).hex,
        kind=kind,
        session_id=str(session_id),
        concept_id=concept,
        dimension=dimension,
        part=DIMENSION_PART.get(dimension),
        outcome=outcome
        if outcome in ("demonstrated", "partial", "not_demonstrated", "unassessable")
        else "demonstrated",
        assisted=payload.get("assistance") not in (None, "independent"),
        judge="evidence-pipeline",
        reason=str(payload.get("reason") or ""),
        occurred_at=occurred_at,
    )


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


_feed: GrowthFeed | None = None


def get_growth_feed() -> GrowthFeed:
    global _feed
    if _feed is None:
        _feed = DbGrowthFeed()
    return _feed


# ------------------------------------------------------------------------------------- SSE


def format_sse(cursor: str, event: GrowthEvent) -> str:
    data = json.dumps(event.model_dump(mode="json", by_alias=True), separators=(",", ":"))
    return f"id: {cursor}\nevent: growth\ndata: {data}\n\n"


async def sse_stream(
    feed: GrowthFeed,
    user_ref: str,
    cursor: str,
    *,
    poll_seconds: float = 1.0,
    heartbeat_seconds: float = 15.0,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
    max_polls: int | None = None,
) -> AsyncIterator[str]:
    """Server-sent events for one learner. Starts with a `retry` hint and a comment so proxies
    flush headers, then emits one `growth` event per feed entry and a heartbeat when idle."""
    yield "retry: 3000\n: connected\n\n"
    last_beat = time.monotonic()
    polls = 0
    while max_polls is None or polls < max_polls:
        polls += 1
        if is_disconnected is not None and await is_disconnected():
            return
        for new_cursor, event in await feed.after(user_ref, cursor):
            cursor = new_cursor
            yield format_sse(new_cursor, event)
            last_beat = time.monotonic()
        if time.monotonic() - last_beat >= heartbeat_seconds:
            yield ": keep-alive\n\n"
            last_beat = time.monotonic()
        await asyncio.sleep(poll_seconds)
