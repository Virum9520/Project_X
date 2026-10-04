"""Audit records for privileged actions: actor, action, target, request ID, before/after state.

`LogAuditSink` writes structured log lines (tests, local without a database); `DbAuditSink`
(`sg_core.identity.db`) writes `audit_log`. Callers only depend on `AuditSink`.
"""

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sg_core.logging import get_logger


@dataclass(frozen=True, slots=True)
class AuditEvent:
    actor_id: str
    actor_email: str | None
    action: str
    request_id: str
    status_code: int
    target: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    ip: str | None = None
    user_agent: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class AuditSink(Protocol):
    async def record(self, event: AuditEvent) -> None: ...


class LogAuditSink:
    def __init__(self) -> None:
        self._log = get_logger("sg.audit")

    async def record(self, event: AuditEvent) -> None:
        payload = asdict(event)
        payload["occurred_at"] = event.occurred_at.isoformat()
        self._log.info("audit", **payload)
