"""In-memory stand-ins for the Drona store, shared by the C12 API tests."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from sg_api.drona.growth import (
    GrowthFeed,
    MemoryGrowthFeed,
    get_growth_feed,
)
from sg_api.drona.questions import ConceptRubric
from sg_api.drona.store import BindResult, NewSession, SessionStore, get_session_store
from sg_api.main import create_app
from sg_api.sessions.tool_tokens import HEADER, mint_tool_token
from sg_core.models.enums import SessionStatus
from sg_core.settings import Environment, Settings, get_settings

SETTINGS = Settings(  # type: ignore[call-arg]
    _env_file=None, environment=Environment.TEST, agent_tool_token_secret=SecretStr("x" * 48)
)

BINARY_SEARCH = ConceptRubric(
    key="dsa.binary_search",
    title="Binary search",
    summary="Find a value in sorted data by halving.",
    criteria={
        "explanation": [
            "Explains why the input must be sorted",
            "States the invariant on the low and high pointers",
        ],
        "application": ["Writes the loop with correct bounds"],
        "transfer": ["Applies it to search on an answer range"],
        "misconceptions": ["Binary search works on any list"],
    },
)


@dataclass
class FakeStore:
    concepts: dict[str, ConceptRubric] = field(
        default_factory=lambda: {BINARY_SEARCH.key: BINARY_SEARCH}
    )
    focus: str | None = "dsa.binary_search"
    stored: list[NewSession] = field(default_factory=list)
    ended: list[tuple[str, str, SessionStatus]] = field(default_factory=list)
    bind_result: BindResult = "bound"
    can_store: bool = True
    broken: bool = False

    async def create(self, new: NewSession) -> bool:
        if self.broken:
            raise RuntimeError("db down")
        self.stored.append(new)
        return self.can_store

    async def end(self, clerk_user_id: str, session_id: str, status: SessionStatus) -> bool:
        self.ended.append((clerk_user_id, session_id, status))
        return session_id != "missing"

    async def bind_conversation(
        self, clerk_user_id: str, session_id: str, conversation_id: str
    ) -> BindResult:
        return self.bind_result

    async def session_focus(self, clerk_user_id: str, session_id: str) -> str | None:
        if self.broken:
            raise RuntimeError("db down")
        return self.focus

    async def concept_rubric(self, concept_key: str) -> ConceptRubric | None:
        if self.broken:
            raise RuntimeError("db down")
        return self.concepts.get(concept_key)


def token(conversation_id: str | None = "conv_1", user: str = "user_clerk_1") -> str:
    value, _ = mint_tool_token(
        user_id=user,
        session_id=str(uuid.UUID(int=1)),
        character="drona",
        conversation_id=conversation_id,
        settings=SETTINGS,
    )
    return value


async def make_client(
    store: SessionStore | None = None,
    feed: GrowthFeed | None = None,
) -> AsyncIterator[AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[get_session_store] = lambda: store or FakeStore()
    app.dependency_overrides[get_growth_feed] = lambda: feed or MemoryGrowthFeed()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


TOKEN_HEADER = HEADER
