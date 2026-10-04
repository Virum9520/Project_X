"""Response and request models for the owner-console API (`/v1/admin/*`).

Mirrored by hand in `packages/contracts/src/admin.ts`; keep both sides in sync. Money is USD as
floats rounded to micro-dollars (display, not accounting). Learner emails are masked wherever the
caller does not need the full address.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

CostGroupBy = Literal["component", "provider", "model", "cost_center", "user"]
COST_GROUP_BY: tuple[str, ...] = ("component", "provider", "model", "cost_center", "user")

TestProfile = Literal["fresh_learner", "returning_learner", "interview_ready"]
TEST_PROFILES: tuple[str, ...] = ("fresh_learner", "returning_learner", "interview_ready")


# ── Overview ──
class BudgetStatus(BaseModel):
    key: str
    limit_usd: float
    committed_usd: float


class Freshness(BaseModel):
    """When each source last produced data. None means it has never produced any."""

    usage_events_at: datetime | None
    cost_entries_at: datetime | None
    sessions_at: datetime | None
    provider_events_at: datetime | None


class Overview(BaseModel):
    generated_at: datetime
    period: str  # YYYY-MM, UTC
    active_users_30d: int
    completed_sessions_30d: int
    spend_month_to_date_usd: float
    projected_month_end_usd: float
    spend_by_cost_center: dict[str, float]
    failed_sessions_7d: int
    failed_calls_7d: int
    failed_provider_events: int
    developer_budget: BudgetStatus | None
    freshness: Freshness
    cost_basis: str = (
        "cost_entries with superseded_by_id IS NULL (estimated, provider or reconciled)"
    )


# ── Users ──
class UserRow(BaseModel):
    id: str
    email_masked: str
    display_name: str | None
    created_at: datetime
    onboarded: bool
    sessions: int
    spend_month_to_date_usd: float


class UserPage(BaseModel):
    items: list[UserRow]
    total: int
    limit: int
    offset: int


class ScheduleInfo(BaseModel):
    id: str
    channel: str
    destination_masked: str | None
    destination_verified: bool
    tz: str
    local_time: str
    days: list[int]
    enabled: bool
    max_duration_seconds: int
    consent_ver: str


class ConsentInfo(BaseModel):
    consent_ver: str
    phrase_verified: bool
    has_voice: bool
    created_at: datetime
    revoked_at: datetime | None


class UserSessionRow(BaseModel):
    id: str
    character: str
    mode: str
    status: str
    is_test: bool
    started_at: datetime | None
    duration_seconds: int | None


class UserDetail(BaseModel):
    id: str
    email_masked: str
    display_name: str | None
    timezone: str | None
    created_at: datetime
    deleted_at: datetime | None
    major: str | None
    experience_level: str | None
    target_role: str | None
    onboarded_at: datetime | None
    plant_status_counts: dict[str, int]
    sessions_total: int
    open_disputes: int
    spend_month_to_date_usd: float
    spend_by_component: dict[str, float]
    budget: BudgetStatus
    schedules: list[ScheduleInfo]
    voice_consent: ConsentInfo | None
    recent_sessions: list[UserSessionRow]


# ── Costs ──
class CostGroup(BaseModel):
    key: str
    label: str
    usd: float
    entries: int


class DailyCost(BaseModel):
    day: date
    usd: float


class UsageTotals(BaseModel):
    events: int
    connected_seconds: float
    input_tokens: int
    output_tokens: int
    # Events that reported tokens. The rest are NULL in the ledger, not zero.
    token_reporting_events: int
    sandbox_seconds: float


class CostReport(BaseModel):
    start: date
    end: date
    group_by: CostGroupBy
    total_usd: float
    by_kind: dict[str, float]  # estimated | provider | reconciled
    reconciled_share: float
    groups: list[CostGroup]
    daily: list[DailyCost]
    usage: UsageTotals
    basis: str = "cost_entries with superseded_by_id IS NULL"


# ── Calls ──
class CallRow(BaseModel):
    occurrence_id: str
    kind: Literal["scheduled", "test"]
    request_id: str | None
    user_masked: str | None
    state: str
    channel: str | None
    scheduled_for: datetime
    attempt_no: int | None
    el_conversation_id: str | None
    twilio_call_sid: str | None
    error: str | None
    ended_at: datetime | None


class CallsReport(BaseModel):
    generated_at: datetime
    upcoming: list[CallRow]
    active: list[CallRow]
    recent: list[CallRow]
    state_counts_7d: dict[str, int]


class AgentRow(BaseModel):
    character: str
    agent_id: str | None
    configured: bool
    sessions_30d: int
    failed_30d: int
    test_sessions_30d: int
    avg_duration_seconds: float | None
    versions: list[str]


class CallNowOptions(BaseModel):
    agents: list[AgentRow]
    targets: list[str]
    test_profiles: list[str]
    max_duration_seconds: int
    min_duration_seconds: int
    cooldown_seconds: int
    cost_per_minute_usd: float | None
    developer_budget: BudgetStatus | None
    dispatcher: str


class CallNowRequest(BaseModel):
    # Client-generated idempotency key: a repeated click re-sends the same id and never re-dials.
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    agent: str = Field(min_length=1, max_length=32)
    agent_version: str | None = Field(default=None, max_length=128)
    target: str = Field(min_length=1, max_length=32)
    test_profile: TestProfile = "fresh_learner"
    duration_seconds: int = Field(ge=30, le=3600)


class CallNowResult(BaseModel):
    replayed: bool
    occurrence_id: str
    attempt_id: str | None
    request_id: str
    state: str
    channel: str
    target: str
    agent: str
    duration_seconds: int
    estimated_cost_usd: float | None
    el_conversation_id: str | None
    detail: str | None = None


# ── Quality and operations ──
class FailedEvent(BaseModel):
    id: str
    provider: str
    event_type: str
    attempts: int
    error: str | None
    received_at: datetime


class QualityReport(BaseModel):
    generated_at: datetime
    assessments_by_status: dict[str, int]
    judge_backlog: int
    oldest_pending_assessment_age_s: float | None
    open_disputes: int
    resolved_disputes: int
    disputes_upheld: int
    # Upheld disputes / resolved disputes: the learner-visible proxy for judge error until the
    # human-labelled calibration set exists (C23). None while nothing is resolved.
    disagreement_rate: float | None
    provider_events_by_status: dict[str, int]
    webhook_oldest_unprocessed_age_s: float | None
    webhook_avg_latency_s_24h: float | None
    failed_events: list[FailedEvent]
    failed_sessions_7d: int
    interrupted_sessions_7d: int


class ComponentStatus(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class SystemStatus(BaseModel):
    generated_at: datetime
    environment: str
    git_sha: str | None
    components: list[ComponentStatus]
    # Booleans only: secrets are never returned.
    configured: dict[str, bool]


# ── Audit ──
class AuditRow(BaseModel):
    id: str
    occurred_at: datetime
    actor_type: str
    actor_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    request_id: str | None
    status_code: int | None
    before: dict[str, object] | None
    after: dict[str, object] | None


class AuditPage(BaseModel):
    items: list[AuditRow]
    next_before: datetime | None
