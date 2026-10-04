"""The call dispatcher: occurrence -> attempt state machine, accept/complete and the sweeper.

Order of work for a due occurrence (the build plan's): claim it (SCHEDULED -> QUEUED, atomic),
reserve a call slot and a budget hold, recheck consent, quiet hours and cancellation, and only
then hand it to the `CallChannel`. Every exit before a connected call releases the hold. An
unanswered call is `missed` and is never redialled; a call whose fate we lost is `unknown`.

Idempotency: claiming is atomic, the budget hold is keyed by occurrence, state changes are
compare-and-set, and the occurrence key `(schedule, local_date)` stops duplicates upstream, so a
retried or concurrent run cannot ring someone twice.
"""

import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sg_core.accountability.budget import BudgetExceededError, BudgetGuard
from sg_core.accountability.channels import CallChannel, DispatchRequest, DispatchResult
from sg_core.accountability.scheduling import in_quiet_hours, parse_hhmm
from sg_core.accountability.states import ACTIVE, TERMINAL
from sg_core.accountability.store import AccountabilityStore
from sg_core.logging import get_logger
from sg_core.models.accountability import CallAttempt, CallOccurrence, CallSchedule
from sg_core.models.enums import CallChannelKind, CallState
from sg_core.settings import Settings

log = get_logger(__name__)

DISPATCH_STALE = timedelta(minutes=2)
QUEUE_STALE = timedelta(minutes=5)
END_GRACE = timedelta(seconds=90)


@dataclass(frozen=True, slots=True)
class DispatchPolicy:
    consent_version: str = "bhima-calls-v1"
    quiet_start: str = "21:30"
    quiet_end: str = "08:00"
    ring_timeout: timedelta = timedelta(seconds=45)
    late_grace: timedelta = timedelta(minutes=20)
    max_concurrent: int = 5
    cost_per_minute_usd: Decimal = Decimal("0.12")
    default_max_duration_seconds: int = 120

    def estimate_usd(self, seconds: int) -> Decimal:
        return (self.cost_per_minute_usd * Decimal(seconds) / Decimal(60)).quantize(
            Decimal("0.000001")
        )


def policy_from_settings(settings: Settings) -> DispatchPolicy:
    return DispatchPolicy(
        consent_version=settings.bhima_consent_version,
        quiet_start=settings.bhima_quiet_start,
        quiet_end=settings.bhima_quiet_end,
        ring_timeout=timedelta(seconds=settings.bhima_ring_timeout_seconds),
        late_grace=timedelta(seconds=settings.bhima_late_grace_seconds),
        max_concurrent=settings.bhima_max_concurrent_calls,
        cost_per_minute_usd=settings.bhima_cost_per_minute_usd,
    )


class CallNotAcceptable(Exception):
    """The learner cannot join this call. `reason` is a stable code for the API."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(slots=True)
class DispatchReport:
    outcomes: Counter[str]

    def __getitem__(self, key: str) -> int:
        return self.outcomes[key]


class CallDispatcher:
    def __init__(
        self,
        store: AccountabilityStore,
        budget: BudgetGuard,
        channels: Mapping[CallChannelKind, CallChannel],
        policy: DispatchPolicy,
    ) -> None:
        self._store = store
        self._budget = budget
        self._channels = channels
        self._policy = policy

    # ── dispatch ──
    async def run_once(self, now: datetime | None = None, limit: int = 20) -> DispatchReport:
        now = now or datetime.now(UTC)
        report = DispatchReport(Counter())
        for occurrence in await self._store.claim_due(now, limit):
            try:
                outcome = await self._process(occurrence, now)
            except Exception:  # one bad occurrence must not stall the rest of the batch
                log.exception("dispatcher.process_failed", occurrence_id=str(occurrence.id))
                outcome = "error"
            report.outcomes[outcome] += 1
        return report

    async def _process(self, occurrence: CallOccurrence, now: datetime) -> str:
        policy = self._policy
        if now - occurrence.scheduled_for > policy.late_grace:
            await self._store.transition_occurrence(
                occurrence.id, {CallState.QUEUED}, CallState.MISSED
            )
            return "missed_late"
        if occurrence.user_id is None:
            await self._store.transition_occurrence(
                occurrence.id, {CallState.QUEUED}, CallState.CANCELLED
            )
            return "cancelled:no_user"

        schedule: CallSchedule | None = None
        if not occurrence.is_test:
            schedule = (
                await self._store.get_schedule(occurrence.schedule_id)
                if occurrence.schedule_id
                else None
            )
        channel_kind = schedule.channel if schedule is not None else CallChannelKind.WEB
        max_seconds = (
            schedule.max_duration_seconds
            if schedule is not None
            else policy.default_max_duration_seconds
        )

        # 1. A slot and a budget hold.
        if await self._store.active_attempt_count() >= policy.max_concurrent:
            await self._store.transition_occurrence(
                occurrence.id, {CallState.QUEUED}, CallState.SCHEDULED
            )
            return "no_slot"
        try:
            await self._budget.reserve(
                occurrence_id=occurrence.id,
                user_id=occurrence.user_id,
                is_test=occurrence.is_test,
                amount_usd=policy.estimate_usd(max_seconds),
                ttl=policy.ring_timeout + timedelta(seconds=max_seconds) + timedelta(minutes=5),
            )
        except BudgetExceededError as exc:
            attempt = await self._store.add_attempt(
                occurrence_id=occurrence.id, channel=channel_kind
            )
            await self._store.transition_attempt(
                attempt.id, {CallState.QUEUED}, CallState.FAILED, error="budget_exceeded"
            )
            await self._store.transition_occurrence(
                occurrence.id, {CallState.QUEUED}, CallState.FAILED
            )
            log.info(
                "dispatcher.budget_exceeded", occurrence_id=str(occurrence.id), detail=str(exc)
            )
            return "budget_exceeded"

        # 2. Recheck consent, quiet hours and cancellation after the (slower) reservation.
        reason = self._recheck(occurrence, schedule, now)
        if reason is not None:
            await self._budget.release(occurrence.id)
            await self._store.transition_occurrence(
                occurrence.id, {CallState.QUEUED}, CallState.CANCELLED
            )
            return f"cancelled:{reason}"

        # 3. Dispatch through the channel.
        if not await self._store.transition_occurrence(
            occurrence.id, {CallState.QUEUED}, CallState.DISPATCHING
        ):  # cancelled or swept while we were working
            await self._budget.release(occurrence.id)
            return "cancelled:state_changed"
        attempt = await self._store.add_attempt(occurrence_id=occurrence.id, channel=channel_kind)
        await self._store.transition_attempt(
            attempt.id, {CallState.QUEUED}, CallState.DISPATCHING, dispatched_at=now
        )
        channel = self._channels.get(channel_kind)
        if channel is None:
            result = DispatchResult(state=CallState.FAILED, error="channel_unavailable")
        else:
            try:
                result = await channel.dispatch(
                    DispatchRequest(
                        attempt_id=attempt.id,
                        occurrence_id=occurrence.id,
                        user_id=occurrence.user_id,
                        max_duration_seconds=max_seconds,
                        destination=schedule.destination if schedule else None,
                        tone=schedule.tone if schedule else None,
                    )
                )
            except Exception as exc:  # provider failure: fail the call, never redial
                log.warning("dispatcher.channel_failed", attempt_id=str(attempt.id), error=str(exc))
                result = DispatchResult(state=CallState.FAILED, error=f"channel_error: {exc}"[:500])

        if result.state is CallState.RINGING:
            await self._store.transition_attempt(
                attempt.id,
                {CallState.DISPATCHING},
                CallState.RINGING,
                **result.attempt_fields,
            )
            await self._store.transition_occurrence(
                occurrence.id, {CallState.DISPATCHING}, CallState.RINGING
            )
            return "ringing"
        final = result.state if result.state in TERMINAL else CallState.FAILED
        await self._store.transition_attempt(
            attempt.id, {CallState.DISPATCHING}, final, error=result.error, ended_at=now
        )
        await self._store.transition_occurrence(occurrence.id, {CallState.DISPATCHING}, final)
        await self._budget.release(occurrence.id)
        return f"failed:{result.error or final.value}"

    def _recheck(
        self, occurrence: CallOccurrence, schedule: CallSchedule | None, now: datetime
    ) -> str | None:
        if occurrence.is_test:
            return None
        if schedule is None:
            return "schedule_deleted"
        if not schedule.enabled:
            return "schedule_disabled"
        if schedule.consent_ver != self._policy.consent_version:
            return "consent_stale"
        if in_quiet_hours(
            now,
            schedule.tz,
            parse_hhmm(self._policy.quiet_start),
            parse_hhmm(self._policy.quiet_end),
        ):
            return "quiet_hours"
        if schedule.channel is CallChannelKind.PHONE and schedule.destination_verified_at is None:
            return "destination_unverified"
        return None

    # ── lifecycle ──
    async def accept(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID, now: datetime | None = None
    ) -> CallAttempt:
        """Learner picks up: RINGING -> CONNECTED. Raises `CallNotAcceptable`."""
        now = now or datetime.now(UTC)
        attempt = await self._store.get_attempt(attempt_id)
        occurrence = await self._store.get_occurrence(attempt.occurrence_id) if attempt else None
        if attempt is None or occurrence is None or occurrence.user_id != user_id:
            raise CallNotAcceptable("not_found")  # same answer for someone else's call
        if attempt.state is not CallState.RINGING:
            raise CallNotAcceptable("not_ringing")
        if (
            attempt.dispatched_at is not None
            and now - attempt.dispatched_at > self._policy.ring_timeout
        ):
            raise CallNotAcceptable("expired")
        if not await self._store.transition_attempt(
            attempt_id, {CallState.RINGING}, CallState.CONNECTED, connected_at=now
        ):
            raise CallNotAcceptable("not_ringing")  # lost a race with a timeout or a second tap
        await self._store.transition_occurrence(
            occurrence.id, {CallState.RINGING}, CallState.CONNECTED
        )
        refreshed = await self._store.get_attempt(attempt_id)
        assert refreshed is not None
        return refreshed

    async def decline(
        self, attempt_id: uuid.UUID, user_id: uuid.UUID, now: datetime | None = None
    ) -> bool:
        now = now or datetime.now(UTC)
        attempt = await self._store.get_attempt(attempt_id)
        occurrence = await self._store.get_occurrence(attempt.occurrence_id) if attempt else None
        if attempt is None or occurrence is None or occurrence.user_id != user_id:
            return False
        return await self._end(
            attempt, CallState.CANCELLED, {CallState.RINGING}, now, error="declined"
        )

    async def attach_conversation(self, attempt_id: uuid.UUID, conversation_id: str | None) -> None:
        if conversation_id:
            await self._store.update_attempt(attempt_id, el_conversation_id=conversation_id)

    async def fail_connected(
        self, attempt_id: uuid.UUID, error: str, now: datetime | None = None
    ) -> bool:
        """The session could not start after the learner accepted."""
        attempt = await self._store.get_attempt(attempt_id)
        if attempt is None:
            return False
        return await self._end(
            attempt, CallState.FAILED, {CallState.CONNECTED}, now or datetime.now(UTC), error=error
        )

    async def complete(
        self,
        attempt_id: uuid.UUID,
        *,
        duration_seconds: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        """The call ended normally (client signal, webhook or reconciliation). Idempotent."""
        now = now or datetime.now(UTC)
        attempt = await self._store.get_attempt(attempt_id)
        if attempt is None:
            return False
        return await self._end(
            attempt,
            CallState.COMPLETED,
            {CallState.CONNECTED, CallState.UNKNOWN},
            now,
            duration_seconds=duration_seconds,
        )

    async def _end(
        self,
        attempt: CallAttempt,
        new: CallState,
        expected: set[CallState],
        now: datetime,
        *,
        error: str | None = None,
        duration_seconds: int | None = None,
    ) -> bool:
        fields: dict[str, object] = {"ended_at": now}
        if error is not None:
            fields["error"] = error
        if not await self._store.transition_attempt(attempt.id, expected, new, **fields):
            return False
        await self._store.transition_occurrence(attempt.occurrence_id, expected | ACTIVE, new)
        if new is CallState.COMPLETED:
            seconds = duration_seconds
            if seconds is None and attempt.connected_at is not None:
                seconds = int((now - attempt.connected_at).total_seconds())
            occurrence = await self._store.get_occurrence(attempt.occurrence_id)
            schedule = (
                await self._store.get_schedule(occurrence.schedule_id)
                if occurrence is not None and occurrence.schedule_id
                else None
            )
            cap = (
                schedule.max_duration_seconds
                if schedule
                else self._policy.default_max_duration_seconds
            )
            billed = min(max(seconds or 0, 0), cap + int(END_GRACE.total_seconds()))
            await self._budget.settle(attempt.occurrence_id, self._policy.estimate_usd(billed))
        else:
            await self._budget.release(attempt.occurrence_id)
        return True

    # ── sweeper ──
    async def sweep(self, now: datetime | None = None) -> DispatchReport:
        """Time out unanswered rings, and recover calls whose fate we lost. Idempotent."""
        now = now or datetime.now(UTC)
        report = DispatchReport(Counter())
        policy = self._policy

        for attempt in await self._store.attempts_in_state(
            CallState.RINGING, now - policy.ring_timeout
        ):
            final = (
                CallState.MISSED if attempt.channel is CallChannelKind.WEB else CallState.UNANSWERED
            )
            if await self._end(attempt, final, {CallState.RINGING}, now, error="ring_timeout"):
                channel = self._channels.get(attempt.channel)
                if channel is not None:
                    await channel.cancel(attempt.id)
                report.outcomes[final.value] += 1

        for attempt in await self._store.attempts_in_state(CallState.CONNECTED, now):
            occurrence = await self._store.get_occurrence(attempt.occurrence_id)
            schedule = (
                await self._store.get_schedule(occurrence.schedule_id)
                if occurrence is not None and occurrence.schedule_id
                else None
            )
            cap = schedule.max_duration_seconds if schedule else policy.default_max_duration_seconds
            started = attempt.connected_at or attempt.updated_at
            # No end signal arrived. Treat the money as spent (settle the full estimate), keep
            # the state honest, and let a late webhook upgrade it to completed.
            if now - started > timedelta(seconds=cap) + END_GRACE and (
                await self._store.transition_attempt(
                    attempt.id, {CallState.CONNECTED}, CallState.UNKNOWN, error="no_end_signal"
                )
            ):
                await self._store.transition_occurrence(
                    attempt.occurrence_id, {CallState.CONNECTED}, CallState.UNKNOWN
                )
                await self._budget.settle(attempt.occurrence_id, policy.estimate_usd(cap))
                report.outcomes["unknown"] += 1

        for attempt in await self._store.attempts_in_state(
            CallState.DISPATCHING, now - DISPATCH_STALE
        ):
            if await self._store.transition_attempt(
                attempt.id, {CallState.DISPATCHING}, CallState.UNKNOWN, error="dispatch_interrupted"
            ):
                await self._store.transition_occurrence(
                    attempt.occurrence_id, {CallState.DISPATCHING}, CallState.UNKNOWN
                )
                await self._budget.release(attempt.occurrence_id)  # never reached a provider
                report.outcomes["unknown"] += 1

        for occurrence in await self._store.occurrences_in_state(
            CallState.DISPATCHING, now - DISPATCH_STALE
        ):
            if not await self._store.attempts_for_occurrence(
                occurrence.id
            ) and await self._store.transition_occurrence(
                occurrence.id, {CallState.DISPATCHING}, CallState.FAILED
            ):
                await self._budget.release(occurrence.id)
                report.outcomes["failed"] += 1

        for occurrence in await self._store.occurrences_in_state(
            CallState.QUEUED, now - QUEUE_STALE
        ):
            attempts = await self._store.attempts_for_occurrence(occurrence.id)
            if attempts:
                for attempt in attempts:
                    await self._store.transition_attempt(
                        attempt.id,
                        {CallState.QUEUED},
                        CallState.FAILED,
                        error="dispatch_interrupted",
                    )
                if await self._store.transition_occurrence(
                    occurrence.id, {CallState.QUEUED}, CallState.FAILED
                ):
                    await self._budget.release(occurrence.id)
                    report.outcomes["failed"] += 1
            elif await self._store.transition_occurrence(
                occurrence.id, {CallState.QUEUED}, CallState.SCHEDULED
            ):
                await self._budget.release(occurrence.id)
                report.outcomes["requeued"] += 1
        return report


async def request_test_call(
    store: AccountabilityStore,
    dispatcher: CallDispatcher,
    *,
    user_id: uuid.UUID,
    request_id: str,
    now: datetime | None = None,
) -> tuple[CallOccurrence, str]:
    """Owner "Call now": a one-off web call with no schedule, deduped on `request_id`.

    It skips the learner's schedule, consent and quiet-hours checks (the owner is testing, on
    the developer budget) but still takes a slot and a budget hold. Returns the occurrence and
    the dispatcher's outcome for it ("ringing", "budget_exceeded", ...).
    """
    now = now or datetime.now(UTC)
    occurrence, created = await store.ensure_test_occurrence(
        request_id=request_id, user_id=user_id, scheduled_for=now
    )
    if not created:
        return occurrence, "duplicate"
    report = await dispatcher.run_once(now)
    outcome = next(iter(report.outcomes), "queued")
    return occurrence, outcome
