"""Usage ledger, costs, budget reservations and pricing (C03).

Unknown token counts stay NULL (never zero). An estimated cost is replaced by its
reconciled entry through `superseded_by_id`, never summed alongside it.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sg_core.models.base import Base, created_at, str_enum, uuid_pk
from sg_core.models.enums import CostCenter, CostKind, ReservationStatus

Money = Numeric(14, 6)


class UsageEvent(Base):
    """TimescaleDB hypertable partitioned on `occurred_at` (see the baseline migration).

    Idempotent on (`idempotency_key`, `occurred_at`); unique indexes on a hypertable must
    include the time column.
    """

    __tablename__ = "usage_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", "occurred_at"),
        Index("uq_usage_events_idempotency", "idempotency_key", "occurred_at", unique=True),
        Index("ix_usage_events_occurred_at", text("occurred_at DESC")),
        Index("ix_usage_events_user_occurred", "user_id", text("occurred_at DESC")),
        Index("ix_usage_events_provider_occurred", "provider", text("occurred_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(server_default=text("gen_random_uuid()"))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    idempotency_key: Mapped[str] = mapped_column(String(256))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    cost_center: Mapped[CostCenter] = mapped_column(str_enum(CostCenter, "cost_center"))
    component: Mapped[str] = mapped_column(String(64))  # drona_session, judge, embeddings, ...
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    environment: Mapped[str] = mapped_column(String(16))
    external_ref: Mapped[str | None] = mapped_column(String(256))  # call/job/request id
    # Measured units in provider-native terms. NULL means "not reported", not zero.
    connected_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    billable_units: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    billable_unit: Mapped[str | None] = mapped_column(String(32))
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_read_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_write_tokens: Mapped[int | None] = mapped_column(BigInteger)
    reasoning_tokens: Mapped[int | None] = mapped_column(BigInteger)
    sandbox_seconds: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    storage_bytes: Mapped[int | None] = mapped_column(BigInteger)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class PricingVersion(Base):
    __tablename__ = "pricing_versions"
    __table_args__ = (Index("ix_pricing_versions_lookup", "provider", "sku", "effective_from"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(32))
    sku: Mapped[str] = mapped_column(String(128))  # e.g. agent_minute, model id + token kind
    unit: Mapped[str] = mapped_column(String(32))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 9))
    currency: Mapped[str] = mapped_column(String(3), server_default="USD")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class CostEntry(Base):
    __tablename__ = "cost_entries"
    __table_args__ = (
        Index("ix_cost_entries_usage_event", "usage_event_id"),
        Index("ix_cost_entries_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # Soft reference: usage_events is a hypertable, so no FK.
    usage_event_id: Mapped[uuid.UUID | None] = mapped_column()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    cost_center: Mapped[CostCenter] = mapped_column(str_enum(CostCenter, "cost_center"))
    component: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    kind: Mapped[CostKind] = mapped_column(str_enum(CostKind, "kind"))
    native_amount: Mapped[Decimal] = mapped_column(Numeric(18, 9))
    native_unit: Mapped[str] = mapped_column(String(32))
    native_currency: Mapped[str | None] = mapped_column(String(3))
    usd_amount: Mapped[Decimal] = mapped_column(Money)
    pricing_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pricing_versions.id", ondelete="RESTRICT")
    )
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cost_entries.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"
    __table_args__ = (Index("ix_budget_reservations_key_status", "budget_key", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    # e.g. "user:<uuid>:2026-10" or "developer:2026-10"
    budget_key: Mapped[str] = mapped_column(String(128))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    cost_center: Mapped[CostCenter] = mapped_column(str_enum(CostCenter, "cost_center"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    call_occurrence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("call_occurrences.id", ondelete="SET NULL")
    )
    reserved_usd: Mapped[Decimal] = mapped_column(Money)
    settled_usd: Mapped[Decimal | None] = mapped_column(Money)
    status: Mapped[ReservationStatus] = mapped_column(
        str_enum(ReservationStatus, "status"), server_default=ReservationStatus.RESERVED.value
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SharedAllocation(Base):
    """Fixed infrastructure cost for a period and how it is spread across active users."""

    __tablename__ = "shared_allocations"

    id: Mapped[uuid.UUID] = uuid_pk()
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(64))
    amount_usd: Mapped[Decimal] = mapped_column(Money)
    allocation_rule: Mapped[str] = mapped_column(String(64))
    denominator_definition: Mapped[str] = mapped_column(Text)
    denominator_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    created_at: Mapped[datetime] = created_at()
