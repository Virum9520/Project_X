"""What an adapter reports about one provider call, and how to hand it to the ledger."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from sg_core.models.enums import CostCenter


@dataclass(frozen=True, slots=True)
class UsageContext:
    """Who and why: supplied by the caller of a metered adapter method.

    `idempotency_key` makes a retried call record once. Leave it None for calls that are
    legitimately distinct (a random key is generated).
    """

    cost_center: CostCenter
    component: str
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    idempotency_key: str | None = None
    environment: str | None = None  # defaults to Settings.environment


@dataclass(frozen=True, slots=True)
class UsageMeasure:
    """Provider-native measurements. None means "not reported", never zero."""

    provider: str
    model: str | None = None
    external_ref: str | None = None
    connected_seconds: Decimal | None = None
    billable_units: Decimal | None = None
    billable_unit: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    sandbox_seconds: Decimal | None = None
    storage_bytes: int | None = None
    # Cost the provider itself reported (USD). Recorded as kind=provider instead of estimated.
    reported_cost_usd: Decimal | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class UsageRecorder(Protocol):
    async def record(
        self, context: UsageContext, measure: UsageMeasure, *, occurred_at: datetime | None = None
    ) -> None: ...


class NullUsageRecorder:
    async def record(
        self, context: UsageContext, measure: UsageMeasure, *, occurred_at: datetime | None = None
    ) -> None:
        return None


class InMemoryUsageRecorder:
    """Test double: keeps what was recorded."""

    def __init__(self) -> None:
        self.records: list[tuple[UsageContext, UsageMeasure]] = []

    async def record(
        self, context: UsageContext, measure: UsageMeasure, *, occurred_at: datetime | None = None
    ) -> None:
        self.records.append((context, measure))
