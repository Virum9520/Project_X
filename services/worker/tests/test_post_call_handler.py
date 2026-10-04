"""The `elevenlabs/post_call_transcription` handler: registration, wiring and failure behaviour."""

import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core" / "tests"))

from evidence_fixtures import (
    BS,
    CONV,
    T0,
    ScriptedLLM,
    World,
    judge_body,
    payload,
    verdict,
)

from sg_core.evidence import LLMJudge, PipelineDeps
from sg_core.models.sessions import ProviderEvent
from sg_core.providers.elevenlabs import ConversationDetails
from sg_core.rules import load_profile
from sg_worker import post_call
from sg_worker.provider_events import handlers


def event(data: Any) -> ProviderEvent:
    body = {"type": "post_call_transcription", "data": data}
    return ProviderEvent(
        id=uuid.uuid4(),
        provider="elevenlabs",
        event_id=f"post_call_transcription:{CONV}",
        event_type="post_call_transcription",
        signature_verified=True,
        payload=body,
    )


class Conversations:
    def __init__(self) -> None:
        self.usage: list[tuple[str, Any]] = []

    async def get_conversation(self, conversation_id: str) -> ConversationDetails:
        return ConversationDetails(conversation_id=conversation_id)

    async def record_conversation_usage(self, conversation_id: str, usage: Any) -> None:
        self.usage.append((conversation_id, usage))


def install(monkeypatch: pytest.MonkeyPatch, deps: PipelineDeps) -> None:
    @asynccontextmanager
    async def factory(_session: AsyncSession) -> AsyncIterator[PipelineDeps]:
        yield deps

    monkeypatch.setattr(post_call, "runtime_factory", factory)


def make_deps(world: World, llm: ScriptedLLM, conversations: Any = None) -> PipelineDeps:
    return PipelineDeps(
        store=world.store,
        judge=LLMJudge(llm, "judge-model"),
        conversations=conversations,
        profile_for=lambda demo: load_profile("normal"),
        clock=lambda: T0,
    )


def test_handler_is_registered_for_post_call_transcription_only() -> None:
    assert (
        handlers.get("elevenlabs", "post_call_transcription")
        is post_call.handle_post_call_transcription
    )
    # The audio webhook is intentionally ignored by the processor.
    assert handlers.get("elevenlabs", "post_call_audio") is None


def test_the_worker_task_module_registers_the_handler() -> None:
    import importlib

    try:
        tasks = importlib.import_module("sg_worker.tasks")
    except RuntimeError as exc:  # embedded Hatchet cannot be downloaded in offline sandboxes
        pytest.skip(str(exc))
    assert tasks.post_call is post_call


async def test_handler_runs_the_pipeline_and_ledgers_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    await world.start_session()
    conversations = Conversations()
    install(
        monkeypatch, make_deps(world, ScriptedLLM(judge_body(verdict(family="h"))), conversations)
    )
    await post_call.handle_post_call_transcription(None, event(payload()))  # type: ignore[arg-type]
    assert len(world.store.revisions) == 1
    [(conv, usage)] = conversations.usage
    assert conv == CONV and usage.user_id == world.user_id and usage.component == "voice.session"


async def test_a_ledger_failure_never_fails_the_event(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    await world.start_session()

    class Broken(Conversations):
        async def record_conversation_usage(self, conversation_id: str, usage: Any) -> None:
            raise RuntimeError("ledger down")

    install(monkeypatch, make_deps(world, ScriptedLLM(judge_body(verdict(family="h"))), Broken()))
    await post_call.handle_post_call_transcription(None, event(payload()))  # type: ignore[arg-type]
    assert len(world.store.revisions) == 1


async def test_payload_without_data_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    install(monkeypatch, make_deps(world, ScriptedLLM(judge_body())))
    with pytest.raises(ValueError, match="no data"):
        await post_call.handle_post_call_transcription(None, event("nope"))  # type: ignore[arg-type]


async def test_unbound_conversation_fails_so_the_job_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sg_core.evidence import SessionNotFoundError

    world = World()
    install(monkeypatch, make_deps(world, ScriptedLLM(judge_body())))
    with pytest.raises(SessionNotFoundError):
        await post_call.handle_post_call_transcription(None, event(payload()))  # type: ignore[arg-type]
    assert BS
