"""What the owner console reads and writes, behind an interface.

`SqlAdminStore` (sql_store.py) is the real thing. Route tests use an in-memory fake, so the
capability, audit and Call now rules are testable without a database.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from sg_api.admin.schemas import (
    AgentRow,
    AuditPage,
    BudgetStatus,
    CallsReport,
    CostGroupBy,
    CostReport,
    Overview,
    QualityReport,
    UserDetail,
    UserPage,
)
from sg_core.models.enums import CallChannelKind, CallState


class CooldownError(Exception):
    """A different Call now was created too recently."""

    def __init__(self, retry_after_s: int) -> None:
        super().__init__(f"call now cooldown: retry in {retry_after_s}s")
        self.retry_after_s = retry_after_s


@dataclass(frozen=True, slots=True)
class TestCallRecord:
    __test__ = False  # not a pytest class

    occurrence_id: uuid.UUID
    attempt_id: uuid.UUID
    request_id: str
    state: CallState
    channel: CallChannelKind
    el_conversation_id: str | None


class AdminStore(Protocol):
    async def ping(self) -> None:
        """Raise if the database is unreachable."""

    async def overview(self, now: datetime) -> Overview: ...

    async def list_users(self, q: str | None, limit: int, offset: int) -> UserPage: ...

    async def get_user(self, user_id: uuid.UUID, now: datetime) -> UserDetail | None: ...

    async def costs(
        self, start: date, end: date, group_by: CostGroupBy, now: datetime
    ) -> CostReport: ...

    async def calls(self, now: datetime) -> CallsReport: ...

    async def agents(self, agent_ids: dict[str, str], now: datetime) -> list[AgentRow]: ...

    async def quality(self, now: datetime) -> QualityReport: ...

    async def audit(
        self,
        *,
        action_prefix: str | None,
        actor_email: str | None,
        before: datetime | None,
        limit: int,
    ) -> AuditPage: ...

    async def developer_budget(self, limit_usd: Decimal, now: datetime) -> BudgetStatus: ...

    # ── Call now ──
    async def create_test_call(
        self,
        *,
        request_id: str,
        channel: CallChannelKind,
        estimate_usd: Decimal,
        budget_limit_usd: Decimal,
        cooldown_s: int,
        now: datetime,
    ) -> tuple[TestCallRecord, bool]:
        """Atomically: replay by `request_id`, else enforce cooldown, hold developer budget and
        insert the test occurrence + first attempt. Returns `(record, created)`.

        Raises `CooldownError` or `sg_core.economics.BudgetExceededError`; nothing is written then.
        """

    async def record_dispatch(
        self,
        record: TestCallRecord,
        *,
        state: CallState,
        el_conversation_id: str | None,
        twilio_call_sid: str | None,
        error: str | None,
        release_budget: bool,
    ) -> None: ...
