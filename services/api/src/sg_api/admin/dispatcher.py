"""The seam between "Call now" and whatever actually places the call.

The owner console only decides *whether* a developer test call may happen (capability, approved
target, cooldown, budget, idempotency) and records it. Placing the call belongs to the call
dispatcher that scheduled calls share (C18: `WebCallChannel`, a `PhoneCallChannel` stub, Twilio
through ElevenLabs). Until C18 lands, `StubCallDispatcher` stands in: it places nothing and
reports the call as queued.

To plug in the real dispatcher, implement `CallDispatcher` and either set
`app.state.call_dispatcher` at startup or override `sg_api.admin.deps.get_call_dispatcher`.

Contract for implementers:
- `dispatch` is called at most once per `request_id` (the console dedupes before calling it).
- Raise `DispatchRejectedError` only when the call was definitely **not** placed (validation,
  quota, provider 4xx). The console then marks the attempt failed and releases the budget hold.
- Any other exception, including a timeout, means the call may have been placed: the console marks
  the attempt `unknown`, keeps the hold, and never retries on its own. Reconcile through the
  provider before another attempt.
- Return the provider correlation IDs when known.
"""

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from sg_core.models.enums import CallChannelKind, CallState


class DispatchRejectedError(Exception):
    """The dispatcher refused the call and nothing was dialled or started."""


@dataclass(frozen=True, slots=True)
class DispatchCommand:
    occurrence_id: uuid.UUID
    attempt_id: uuid.UUID
    request_id: str
    channel: CallChannelKind
    target: str  # "web", or a verified E.164 test number for the phone channel
    agent: str  # character key, e.g. "bhima"
    agent_id: str | None  # ElevenLabs agent ID when configured
    agent_version: str | None
    test_profile: str
    max_duration_seconds: int
    requested_by: str  # Clerk user ID of the admin
    is_test: bool = True  # always true for Call now; test-tagged records, no garden effects


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    state: CallState
    el_conversation_id: str | None = None
    twilio_call_sid: str | None = None
    detail: str | None = None


class CallDispatcher(Protocol):
    name: str

    async def dispatch(self, command: DispatchCommand) -> DispatchOutcome: ...


@dataclass(slots=True)
class StubCallDispatcher:
    """Places no call. Records commands so tests (and the console in local runs) can see them."""

    name: str = "stub"
    sent: list[DispatchCommand] = field(default_factory=list)

    async def dispatch(self, command: DispatchCommand) -> DispatchOutcome:
        self.sent.append(command)
        return DispatchOutcome(
            state=CallState.QUEUED,
            detail="stub dispatcher: no call was placed (the call dispatcher arrives with C18)",
        )
