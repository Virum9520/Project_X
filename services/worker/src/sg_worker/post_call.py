"""Provider-event handler for ElevenLabs `post_call_transcription` (C11).

Starts the evidence pipeline the moment the stored webhook is processed: no batching, so the
garden revision lands within seconds of the call ending. The handler runs in the provider-event
processor's savepoint (see `provider_events.py`), so a failure rolls back every evidence,
assessment, memory and garden write, records the event as `failed`, and Hatchet retries it.

`post_call_audio` is deliberately unhandled (the processor marks it `ignored`): the audio is not
needed for assessment and is never stored by this pipeline.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.economics.usage import UsageContext
from sg_core.evidence import ConversationSource, LLMJudge, PipelineDeps, run_post_call
from sg_core.evidence.db_store import DbEvidenceStore
from sg_core.logging import get_logger
from sg_core.models.enums import CostCenter
from sg_core.models.sessions import ProviderEvent
from sg_core.providers.llm import llm_client_from_settings
from sg_core.settings import get_settings
from sg_worker.provider_events import handlers

log = get_logger(__name__)

PROVIDER = "elevenlabs"
EVENT_TYPE = "post_call_transcription"


@asynccontextmanager
async def default_runtime(session: AsyncSession) -> AsyncIterator[PipelineDeps]:
    """Real providers from settings. The ElevenLabs client is optional: without a key the
    pipeline simply cannot reconcile a webhook that arrived without a transcript."""
    from sg_core.providers.elevenlabs import client_from_settings

    settings = get_settings()
    conversations: Any = None
    try:
        conversations = client_from_settings()
    except RuntimeError:
        log.info("post_call.no_elevenlabs_key")
    async with llm_client_from_settings() as llm:
        try:
            yield PipelineDeps(
                store=DbEvidenceStore(session),
                judge=LLMJudge(llm, settings.judge_model),
                conversations=conversations,
            )
        finally:
            if conversations is not None:
                await conversations.aclose()


# Tests replace this to inject scripted providers and an in-memory-free DB store.
RuntimeFactory = Callable[[AsyncSession], AbstractAsyncContextManager[PipelineDeps]]
runtime_factory: RuntimeFactory = default_runtime


@handlers.register(PROVIDER, EVENT_TYPE)
async def handle_post_call_transcription(session: AsyncSession, event: ProviderEvent) -> None:
    data = event.payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("post_call_transcription payload has no data object")
    async with runtime_factory(session) as deps:
        result = await run_post_call(deps, data)
        log.info(
            "post_call.processed",
            conversation_id=data.get("conversation_id"),
            status=result.status,
            revision=result.revision,
            assessments=result.assessments,
            rejected=len(result.rejected),
        )
        await _record_usage(deps, str(data.get("conversation_id")), result.session_id)


async def _record_usage(deps: PipelineDeps, conversation_id: str, session_id: Any) -> None:
    """Best effort: ledger the call's connected minutes. Idempotent per conversation."""
    source: ConversationSource | None = deps.conversations
    record = getattr(source, "record_conversation_usage", None)
    if record is None or session_id is None:
        return
    try:
        ref = await deps.store.find_session(conversation_id)
        if ref is None:
            return
        await record(
            conversation_id,
            UsageContext(
                cost_center=CostCenter.LEARNER,
                component="voice.session",
                user_id=ref.user_id,
                session_id=ref.id,
                idempotency_key=f"elevenlabs:conversation:{conversation_id}",
            ),
        )
    except Exception as exc:  # never fail the evidence pipeline over a ledger entry
        log.warning("post_call.usage_failed", error=type(exc).__name__)
