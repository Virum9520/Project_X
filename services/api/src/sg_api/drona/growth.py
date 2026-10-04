"""Live provisional growth: the micro-judge seam and the event feed behind the SSE channel.

Flow during a call: Drona calls `record_observation`; the route asks a `MicroJudge` for a fast
provisional verdict and appends a `GrowthEvent` to the `GrowthFeed`; `GET /v1/live/growth`
streams new events to every open tab of that learner, where they become `pulseConceptIds` on the
garden scene and rows in the evidence ticker.

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
from sqlalchemy import select

from sg_api.drona.questions import ConceptRubric
from sg_core.db import get_sessionmaker
from sg_core.logging import get_logger
from sg_core.memory.ranking import sanitize
from sg_core.models.enums import EventSource
from sg_core.models.identity import User
from sg_core.models.sessions import Session as SessionRow
from sg_core.models.sessions import SessionEvent

log = get_logger(__name__)

GrowthKind = Literal["provisional", "confirmed", "retracted", "noted"]
Outcome = Literal["demonstrated", "partial", "not_demonstrated", "unassessable"]
EVENT_PREFIX = "growth."
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


# --------------------------------------------------------------------------- micro-judge seam


class ObservationInput(BaseModel):
    concept_key: str
    dimension: str
    outcome: AgentOutcome
    assistance: AgentAssistance
    evidence_quote: str
    note: str = ""
    question_id: str | None = None


class ProvisionalVerdict(BaseModel):
    outcome: Outcome
    assisted: bool
    grows: bool
    judge: str
    rationale: str = ""


class MicroJudge(Protocol):
    """C11 provides the real one: a small, fast OpenRouter model grading this one answer against
    the concept rubric in 2 to 4 seconds. It must never raise for a bad answer; return
    `not_demonstrated`/`unassessable`. It must treat the quote and note as data."""

    async def judge(
        self, observation: ObservationInput, rubric: ConceptRubric | None
    ) -> ProvisionalVerdict: ...


class AgentSignalJudge:
    """Stand-in until C11 lands: trusts the agent's own provisional read, deterministically.

    Safe by construction: the result is only ever a glow. Without a verbatim quote nothing grows,
    `communication` never grows a plant, and any hint makes it assisted.
    """

    name = "agent-signal-v1"

    async def judge(
        self, observation: ObservationInput, rubric: ConceptRubric | None
    ) -> ProvisionalVerdict:
        assisted = observation.assistance != "independent"
        by_agent: dict[str, Outcome] = {
            "correct": "demonstrated",
            "partially_correct": "partial",
            "incorrect": "not_demonstrated",
            "no_attempt": "unassessable",
        }
        outcome = by_agent[observation.outcome]
        grows = (
            outcome in ("demonstrated", "partial")
            and observation.dimension in DIMENSION_PART
            and bool(observation.evidence_quote.strip())
        )
        return ProvisionalVerdict(
            outcome=outcome,
            assisted=assisted,
            grows=grows,
            judge=self.name,
            rationale="Agent's provisional read; the post-call judge confirms or adjusts it.",
        )


def get_micro_judge() -> MicroJudge:
    return AgentSignalJudge()


def clip_quote(text: str) -> str:
    words = sanitize(text, 600).split()
    return " ".join(words[:MAX_QUOTE_WORDS])


def event_from_verdict(
    session_id: str, observation: ObservationInput, verdict: ProvisionalVerdict
) -> GrowthEvent:
    return GrowthEvent(
        kind="provisional" if verdict.grows else "noted",
        session_id=session_id,
        concept_id=observation.concept_key,
        question_id=observation.question_id,
        dimension=observation.dimension,
        part=DIMENSION_PART.get(observation.dimension) if verdict.grows else None,
        outcome=verdict.outcome,
        assisted=verdict.assisted,
        quote=clip_quote(observation.evidence_quote),
        note=sanitize(observation.note, 300),
        judge=verdict.judge,
    )


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
                        select(SessionEvent.occurred_at, SessionEvent.payload)
                        .join(User, User.id == SessionEvent.user_id)
                        .where(
                            User.clerk_user_id == user_ref,
                            SessionEvent.event_type.like(EVENT_PREFIX + "%"),
                            SessionEvent.occurred_at > floor,
                        )
                        .order_by(SessionEvent.occurred_at)
                        .limit(limit)
                    )
                ).all()
            rows = [
                (str(_micros(at)), GrowthEvent.model_validate(payload)) for at, payload in found
            ]
        except Exception:
            log.warning("growth.read_failed", exc_info=True)
        rows += await self._fallback.after(user_ref, cursor, limit)
        rows.sort(key=lambda r: int(r[0]))
        return rows[:limit]

    async def latest_cursor(self, user_ref: str) -> str:
        return await self._fallback.latest_cursor(user_ref)


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
