"""Worker task registry. Domain workflows (ingestion, judge, dispatch) land here by phase."""

import uuid
from datetime import timedelta
from typing import Any

from hatchet_sdk import Context
from hatchet_sdk.runnables.workflow import BaseWorkflow
from hatchet_sdk.types.idempotency import TTLBasedIdempotencyConfig
from pydantic import BaseModel

from sg_core.db import get_sessionmaker
from sg_worker.client import get_hatchet
from sg_worker.dispatch import PROVIDER_EVENT_KEY
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


ALL_WORKFLOWS: list[BaseWorkflow[Any]] = [ping, process_event]
