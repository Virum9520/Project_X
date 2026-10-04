"""Worker task registry. Domain workflows (ingestion, judge, dispatch) land here by phase."""

from typing import Any

from hatchet_sdk import Context
from hatchet_sdk.runnables.workflow import BaseWorkflow
from pydantic import BaseModel

from sg_worker.client import get_hatchet

hatchet = get_hatchet()


class PingInput(BaseModel):
    message: str = "ping"


class PingOutput(BaseModel):
    message: str


@hatchet.task(name="system.ping", input_validator=PingInput)
async def ping(input: PingInput, ctx: Context) -> PingOutput:
    """Smoke-test task proving the worker is connected and executing."""
    return PingOutput(message=f"pong: {input.message}")


ALL_WORKFLOWS: list[BaseWorkflow[Any]] = [ping]
