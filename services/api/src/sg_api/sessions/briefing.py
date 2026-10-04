"""Session briefing seam. STUB until the Memory Persistence Engine (C09) and curriculum (C07).

The briefing is bounded text sent to the agent as the `briefing` dynamic variable. C09 replaces
`StubBriefingProvider` with a relevance-ranked builder; the interface stays the same.
"""

from typing import Protocol

from pydantic import BaseModel, Field

from sg_api.sessions.identity import Learner

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
        self, learner: Learner, character: str, focus_concept_id: str | None
    ) -> SessionBriefing: ...


class StubBriefingProvider:
    async def build(
        self, learner: Learner, character: str, focus_concept_id: str | None
    ) -> SessionBriefing:
        title = (
            focus_concept_id.rsplit(".", 1)[-1].replace("_", " ").capitalize()
            if focus_concept_id
            else "today's topic"
        )
        return SessionBriefing(
            text="No memories recorded yet. Treat this as the learner's first session.",
            focus_concept=focus_concept_id or "none",
            focus_concept_title=title,
        )


def get_briefing_provider() -> BriefingProvider:
    return StubBriefingProvider()
