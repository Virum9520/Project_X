"""Session briefing seam, backed by the Memory Persistence Engine (`sg_core.memory`, C09).

The briefing is bounded text sent to the agent as the `briefing` dynamic variable and returned by
the `get_briefing` server tool. `MemoryBriefingProvider` is the real implementation;
`StubBriefingProvider` is the degraded fallback when the database is unreachable (a session
without memory beats no session).
"""

from typing import Protocol

from pydantic import BaseModel, Field
from sqlalchemy import select

from sg_api.sessions.identity import Learner
from sg_core.db import get_sessionmaker
from sg_core.logging import get_logger
from sg_core.memory import build_briefing
from sg_core.memory.ranking import sanitize
from sg_core.models.identity import User

log = get_logger(__name__)

# Dynamic variables travel in the WebRTC session start; keep the briefing bounded.
MAX_BRIEFING_CHARS = 4000


class SessionBriefing(BaseModel):
    text: str = Field(max_length=MAX_BRIEFING_CHARS)
    focus_concept: str = "none"
    focus_concept_title: str = "today's topic"
    due_concepts: list[str] = []
    target_role: str = "Software Engineer"


class BriefingProvider(Protocol):
    async def build(
        self,
        learner: Learner,
        character: str,
        focus_concept_id: str | None,
        query_hint: str | None = None,
    ) -> SessionBriefing: ...


class StubBriefingProvider:
    async def build(
        self,
        learner: Learner,
        character: str,
        focus_concept_id: str | None,
        query_hint: str | None = None,
    ) -> SessionBriefing:
        title = (
            focus_concept_id.rsplit(".", 1)[-1].replace("_", " ").capitalize()
            if focus_concept_id
            else "today's topic"
        )
        return SessionBriefing(
            text="No memories recorded yet. Treat this as the learner's first session.",
            focus_concept=sanitize(focus_concept_id, 120) if focus_concept_id else "none",
            focus_concept_title=sanitize(title, 120),
        )


class MemoryBriefingProvider:
    """Builds the briefing from stored memories. `learner.user_id` is the Clerk user ID."""

    def __init__(self, fallback: BriefingProvider | None = None) -> None:
        self._fallback = fallback or StubBriefingProvider()

    async def build(
        self,
        learner: Learner,
        character: str,
        focus_concept_id: str | None,
        query_hint: str | None = None,
    ) -> SessionBriefing:
        try:
            async with get_sessionmaker()() as session:
                user_id = await session.scalar(
                    select(User.id).where(
                        User.clerk_user_id == learner.user_id, User.deleted_at.is_(None)
                    )
                )
                if user_id is None:  # signed in but not synced to `users` yet: first session
                    return await self._fallback.build(
                        learner, character, focus_concept_id, query_hint
                    )
                briefing = await build_briefing(
                    session,
                    user_id=user_id,
                    character=character,
                    focus_concept_key=focus_concept_id,
                    query_hint=query_hint,
                    max_chars=MAX_BRIEFING_CHARS,
                )
        except Exception:
            log.warning("briefing.failed", character=character, exc_info=True)
            return await self._fallback.build(learner, character, focus_concept_id, query_hint)
        # Learner- and client-supplied values become agent dynamic variables: flatten them.
        return SessionBriefing(
            text=briefing.text,
            focus_concept=sanitize(briefing.focus_concept, 120),
            focus_concept_title=sanitize(briefing.focus_concept_title, 120),
            due_concepts=briefing.due_concepts,
            target_role=sanitize(briefing.target_role, 120),
        )


def get_briefing_provider() -> BriefingProvider:
    return MemoryBriefingProvider()
