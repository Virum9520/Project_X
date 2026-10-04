"""Bhima's minute tick: create due occurrences, dispatch them, sweep timeouts.

`run_tick` is plain async code (testable with in-memory fakes); `tasks.py` wraps it in the Hatchet
cron workflow `accountability.tick`. Every step is idempotent, so overlapping or repeated ticks,
a Hatchet retry or two workers are all harmless.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sg_core.accountability import CallDispatcher, materialize_occurrences
from sg_core.accountability.store import AccountabilityStore
from sg_core.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class TickResult:
    created: int = 0
    dispatched: dict[str, int] = field(default_factory=dict)
    swept: dict[str, int] = field(default_factory=dict)


async def run_tick(
    store: AccountabilityStore, dispatcher: CallDispatcher, now: datetime | None = None
) -> TickResult:
    now = now or datetime.now(UTC)
    result = TickResult()
    result.created = await materialize_occurrences(store, now)
    result.dispatched = dict((await dispatcher.run_once(now)).outcomes)
    result.swept = dict((await dispatcher.sweep(now)).outcomes)
    if result.created or result.dispatched or result.swept:
        log.info(
            "accountability.tick",
            created=result.created,
            dispatched=result.dispatched,
            swept=result.swept,
        )
    return result
