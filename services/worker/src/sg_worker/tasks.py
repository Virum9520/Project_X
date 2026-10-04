"""Worker task registry. Domain workflows (ingestion, judge, dispatch) land here by phase."""

import uuid
from datetime import timedelta
from typing import Any

from hatchet_sdk import Context, EmptyModel
from hatchet_sdk.runnables.workflow import BaseWorkflow
from hatchet_sdk.types.idempotency import TTLBasedIdempotencyConfig
from pydantic import BaseModel

from sg_core.accountability import build_dispatcher, db_store
from sg_core.db import get_sessionmaker
from sg_core.economics.budget import expire_stale
from sg_core.knowledge import run_ingestion_job
from sg_core.providers import object_store_from_settings
from sg_core.settings import get_settings
from sg_worker import post_call  # noqa: F401  (registers the post_call_transcription handler)
from sg_worker.accountability import run_tick
from sg_worker.client import get_hatchet
from sg_worker.dispatch import DOCUMENT_INGEST_KEY, PROVIDER_EVENT_KEY
from sg_worker.provider_events import process_provider_event

hatchet = get_hatchet()


class PingInput(BaseModel):
    message: str = "ping"


class PingOutput(BaseModel):
    message: str


@hatchet.task(name="system.ping", input_validator=PingInput)
async def ping(input: PingInput, ctx: Context) -> PingOutput:
    """Smoke-test task proving the worker is connected and executing."""
    return PingOutput(message=f"pong: {input.message}")


class ProviderEventInput(BaseModel):
    provider_event_id: uuid.UUID
    provider: str
    event_type: str


class ProviderEventOutput(BaseModel):
    outcome: str


@hatchet.task(
    name="provider_event.process",
    input_validator=ProviderEventInput,
    on_events=[PROVIDER_EVENT_KEY],
    retries=3,
    backoff_factor=2.0,
    backoff_max_seconds=60,
    execution_timeout=timedelta(minutes=5),
    # Belt: Hatchet drops a second run for the same stored event. Braces: the row lock and
    # terminal-status check inside process_provider_event.
    idempotency=TTLBasedIdempotencyConfig(
        key_expression="input.provider_event_id", ttl=timedelta(hours=24)
    ),
)
async def process_event(input: ProviderEventInput, ctx: Context) -> ProviderEventOutput:
    """Run the registered handler for one stored webhook event."""
    async with get_sessionmaker()() as session:
        outcome = await process_provider_event(session, input.provider_event_id)
    return ProviderEventOutput(outcome=outcome.value)


class IngestDocumentInput(BaseModel):
    document_version_id: uuid.UUID
    request_id: str = ""


class IngestDocumentOutput(BaseModel):
    status: str
    chunks: int = 0
    mappings: int = 0
    detail: str | None = None


@hatchet.task(
    name="knowledge.ingest_document",
    input_validator=IngestDocumentInput,
    on_events=[DOCUMENT_INGEST_KEY],
    retries=3,
    backoff_factor=2.0,
    backoff_max_seconds=120,
    execution_timeout=timedelta(minutes=15),
    idempotency=TTLBasedIdempotencyConfig(
        key_expression="input.request_id", ttl=timedelta(hours=1)
    ),
)
async def ingest_document(input: IngestDocumentInput, ctx: Context) -> IngestDocumentOutput:
    """Extract, map, chunk, embed and activate one uploaded document version.

    Transient provider failures raise (Hatchet retries); permanent ones mark the version
    `failed` with a learner-readable reason and finish normally. The previous active version
    keeps serving until the new one is fully indexed.
    """
    result = await run_ingestion_job(
        get_sessionmaker(), object_store_from_settings(), input.document_version_id
    )
    return IngestDocumentOutput(
        status=result.status.value,
        chunks=result.chunks,
        mappings=result.mappings,
        detail=result.detail,
    )


class TickOutput(BaseModel):
    created: int
    dispatched: dict[str, int]
    swept: dict[str, int]
    expired_holds: int


@hatchet.task(
    name="accountability.tick",
    on_crons=["* * * * *"],
    execution_timeout=timedelta(seconds=55),
    retries=0,  # the next minute's tick is the retry
)
async def accountability_tick(input: EmptyModel, ctx: Context) -> TickOutput:
    """Every minute: create due Bhima call occurrences, dispatch them, time out unanswered rings.

    Also expires stale budget holds (C03 leaves that to a periodic job).
    """
    settings = get_settings()
    store = db_store()
    tick = await run_tick(store, build_dispatcher(store, settings))
    async with get_sessionmaker()() as session, session.begin():
        expired = await expire_stale(session)
    return TickOutput(
        created=tick.created,
        dispatched=tick.dispatched,
        swept=tick.swept,
        expired_holds=expired,
    )


ALL_WORKFLOWS: list[BaseWorkflow[Any]] = [ping, process_event, ingest_document, accountability_tick]
