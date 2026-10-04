"""Call now: an explicit, audited developer test call.

Rules (architecture brief, "Scheduled calls and Call now"):
- Only to an approved target (`CALL_NOW_APPROVED_TARGETS`): the web channel, or a verified test
  number. The browser picks from the approved list; it cannot name another destination.
- Duration is bounded (`CALL_NOW_MAX_DURATION_SECONDS`).
- One idempotent request: the same `request_id` never dials twice, it replays the first outcome.
  A later deliberate test uses a new request ID and must wait out the cooldown.
- The developer budget is reserved atomically before dispatch, never a learner's.
- Records are test-tagged (`is_test`, no learner, no schedule), so they cannot touch a learner's
  garden or consume a scheduled occurrence.
- An ambiguous dispatch (timeout, unexpected error) is `unknown`: the hold stays, no retry.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sg_api.admin.dispatcher import (
    CallDispatcher,
    DispatchCommand,
    DispatchOutcome,
    DispatchRejectedError,
)
from sg_api.admin.schemas import CallNowRequest, CallNowResult
from sg_api.admin.store import AdminStore, CooldownError
from sg_core.economics.budget import BudgetExceededError, monthly_limit_usd
from sg_core.economics.pricing import PriceBook
from sg_core.logging import get_logger
from sg_core.models.enums import CallChannelKind, CallState, Character, CostCenter
from sg_core.settings import Settings

log = get_logger(__name__)

MIN_DURATION_SECONDS = 30
E164 = re.compile(r"^\+[1-9]\d{6,14}$")


class CallNowError(Exception):
    """A refused request. `status_code` maps to HTTP; `detail` is safe to show the admin."""

    def __init__(self, status_code: int, detail: str, *, retry_after_s: int | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.retry_after_s = retry_after_s


@dataclass(frozen=True, slots=True)
class CallNowPlan:
    channel: CallChannelKind
    agent: Character
    agent_id: str | None
    duration_seconds: int
    estimate_usd: Decimal | None


def cost_per_minute(price_book: PriceBook | None = None) -> Decimal | None:
    entry = (price_book or PriceBook()).price("elevenlabs", "agent_minute")
    return entry.unit_price if entry else None


def channel_for(target: str) -> CallChannelKind:
    return CallChannelKind.WEB if target == "web" else CallChannelKind.PHONE


def plan_call(body: CallNowRequest, settings: Settings) -> CallNowPlan:
    """Validate a request against settings. Raises `CallNowError`; has no side effects."""
    approved = settings.call_now_approved_targets
    if body.target not in approved:
        raise CallNowError(403, "target is not an approved test destination")
    if body.target != "web" and not E164.match(body.target):
        raise CallNowError(422, "approved phone targets must be E.164 numbers")
    try:
        agent = Character(body.agent)
    except ValueError:
        raise CallNowError(422, f"unknown agent {body.agent!r}") from None
    max_s = settings.call_now_max_duration_seconds
    if not MIN_DURATION_SECONDS <= body.duration_seconds <= max_s:
        raise CallNowError(
            422, f"duration must be between {MIN_DURATION_SECONDS} and {max_s} seconds"
        )
    per_minute = cost_per_minute()
    estimate = (
        (per_minute * Decimal(body.duration_seconds) / Decimal(60)).quantize(Decimal("0.000001"))
        if per_minute is not None
        else None
    )
    return CallNowPlan(
        channel=channel_for(body.target),
        agent=agent,
        agent_id=settings.elevenlabs_agent_ids.get(agent.value),
        duration_seconds=body.duration_seconds,
        estimate_usd=estimate,
    )


async def call_now(
    *,
    store: AdminStore,
    dispatcher: CallDispatcher,
    settings: Settings,
    body: CallNowRequest,
    requested_by: str,
    now: datetime | None = None,
) -> CallNowResult:
    now = now or datetime.now(UTC)
    plan = plan_call(body, settings)
    # Unpriced calls reserve nothing rather than a made-up amount; the budget still gates spend
    # that is priced, and the cooldown bounds the rate.
    estimate = plan.estimate_usd if plan.estimate_usd is not None else Decimal(0)

    try:
        record, created = await store.create_test_call(
            request_id=body.request_id,
            channel=plan.channel,
            estimate_usd=estimate,
            budget_limit_usd=monthly_limit_usd(CostCenter.DEVELOPER, settings),
            cooldown_s=settings.call_now_cooldown_seconds,
            now=now,
        )
    except CooldownError as exc:
        raise CallNowError(
            429,
            "a test call was started moments ago; wait before another",
            retry_after_s=exc.retry_after_s,
        ) from exc
    except BudgetExceededError as exc:
        raise CallNowError(402, "the developer test-call budget for this month is used up") from exc

    def result(
        state: CallState, conversation_id: str | None, detail: str | None, *, replayed: bool
    ) -> CallNowResult:
        return CallNowResult(
            replayed=replayed,
            occurrence_id=str(record.occurrence_id),
            attempt_id=str(record.attempt_id),
            request_id=record.request_id,
            state=state.value,
            channel=plan.channel.value,
            target=body.target,
            agent=plan.agent.value,
            duration_seconds=plan.duration_seconds,
            estimated_cost_usd=float(plan.estimate_usd) if plan.estimate_usd is not None else None,
            el_conversation_id=conversation_id,
            detail=detail,
        )

    if not created:
        return result(
            record.state,
            record.el_conversation_id,
            "this request ID was already submitted; no new call was placed",
            replayed=True,
        )

    command = DispatchCommand(
        occurrence_id=record.occurrence_id,
        attempt_id=record.attempt_id,
        request_id=record.request_id,
        channel=plan.channel,
        target=body.target,
        agent=plan.agent.value,
        agent_id=plan.agent_id,
        agent_version=body.agent_version,
        test_profile=body.test_profile,
        max_duration_seconds=plan.duration_seconds,
        requested_by=requested_by,
    )
    outcome: DispatchOutcome
    try:
        outcome = await dispatcher.dispatch(command)
    except DispatchRejectedError as exc:
        # Definitely not placed: free the hold.
        await store.record_dispatch(
            record,
            state=CallState.FAILED,
            el_conversation_id=None,
            twilio_call_sid=None,
            error=str(exc)[:300],
            release_budget=True,
        )
        raise CallNowError(502, f"the call was not placed: {exc}") from exc
    except Exception as exc:
        # May have been placed: unknown until reconciled. Keep the hold, never retry here.
        log.error("call_now.dispatch_uncertain", request_id=record.request_id, error=str(exc))
        await store.record_dispatch(
            record,
            state=CallState.UNKNOWN,
            el_conversation_id=None,
            twilio_call_sid=None,
            error=f"dispatch outcome unknown: {type(exc).__name__}",
            release_budget=False,
        )
        return result(
            CallState.UNKNOWN,
            None,
            "dispatch outcome is unknown and will be reconciled; do not retry yet",
            replayed=False,
        )

    await store.record_dispatch(
        record,
        state=outcome.state,
        el_conversation_id=outcome.el_conversation_id,
        twilio_call_sid=outcome.twilio_call_sid,
        error=None,
        release_budget=False,
    )
    return result(outcome.state, outcome.el_conversation_id, outcome.detail, replayed=False)
