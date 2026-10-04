"""Call schedules (learner-owned, consent-gated) and the scheduler that creates occurrences."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from sg_core.accountability.dispatcher import DispatchPolicy
from sg_core.accountability.scheduling import (
    in_quiet_hours,
    load_zone,
    parse_hhmm,
    plan_occurrences,
)
from sg_core.accountability.store import AccountabilityStore
from sg_core.logging import get_logger
from sg_core.models.accountability import CallSchedule
from sg_core.models.enums import CallChannelKind

log = get_logger(__name__)

MIN_CALL_SECONDS = 30
MAX_CALL_SECONDS = 300
MAX_SCHEDULES_PER_USER = 3
TONES = ("energetic", "calm")


class ScheduleRejected(ValueError):
    """The request is invalid. `code` is stable for the API and the UI."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ScheduleSpec:
    tz: str
    local_time: time
    days: list[int]
    channel: CallChannelKind = CallChannelKind.WEB
    tone: str | None = None
    max_duration_seconds: int = 120
    consent_ver: str = ""
    enabled: bool = True


def validate_spec(spec: ScheduleSpec, policy: DispatchPolicy) -> ScheduleSpec:
    if spec.consent_ver != policy.consent_version:
        raise ScheduleRejected(
            "consent_required", "accept the current call consent to schedule calls"
        )
    try:
        load_zone(spec.tz)
    except ValueError as exc:
        raise ScheduleRejected("bad_timezone", str(exc)) from exc
    days = sorted(set(spec.days))
    if not days or days[0] < 1 or days[-1] > 7:
        raise ScheduleRejected("bad_days", "days must be ISO weekdays 1 (Mon) to 7 (Sun)")
    if spec.channel is not CallChannelKind.WEB:
        raise ScheduleRejected("channel_unavailable", "phone calls are not available yet")
    if spec.tone is not None and spec.tone not in TONES:
        raise ScheduleRejected("bad_tone", f"tone must be one of {', '.join(TONES)}")
    if not MIN_CALL_SECONDS <= spec.max_duration_seconds <= MAX_CALL_SECONDS:
        raise ScheduleRejected(
            "bad_duration",
            f"call length must be {MIN_CALL_SECONDS} to {MAX_CALL_SECONDS} seconds",
        )
    # A call time inside the quiet window would be cancelled every day: refuse it up front.
    probe = datetime(
        2026, 1, 15, spec.local_time.hour, spec.local_time.minute, tzinfo=load_zone(spec.tz)
    )
    if in_quiet_hours(probe, spec.tz, parse_hhmm(policy.quiet_start), parse_hhmm(policy.quiet_end)):
        raise ScheduleRejected(
            "quiet_hours",
            f"calls are not placed between {policy.quiet_start} and {policy.quiet_end} local time",
        )
    return ScheduleSpec(
        tz=spec.tz,
        local_time=spec.local_time.replace(second=0, microsecond=0, tzinfo=None),
        days=days,
        channel=spec.channel,
        tone=spec.tone,
        max_duration_seconds=spec.max_duration_seconds,
        consent_ver=spec.consent_ver,
        enabled=spec.enabled,
    )


async def create_schedule(
    store: AccountabilityStore, user_id: uuid.UUID, spec: ScheduleSpec, policy: DispatchPolicy
) -> CallSchedule:
    spec = validate_spec(spec, policy)
    if len(await store.list_schedules(user_id)) >= MAX_SCHEDULES_PER_USER:
        raise ScheduleRejected("too_many", f"at most {MAX_SCHEDULES_PER_USER} call schedules")
    return await store.add_schedule(
        CallSchedule(
            id=uuid.uuid4(),
            user_id=user_id,
            channel=spec.channel,
            tz=spec.tz,
            local_time=spec.local_time,
            days=spec.days,
            tone=spec.tone,
            max_duration_seconds=spec.max_duration_seconds,
            consent_ver=spec.consent_ver,
            enabled=spec.enabled,
        )
    )


async def update_schedule(
    store: AccountabilityStore,
    user_id: uuid.UUID,
    schedule_id: uuid.UUID,
    spec: ScheduleSpec,
    policy: DispatchPolicy,
) -> CallSchedule | None:
    schedule = await store.get_schedule(schedule_id)
    if schedule is None or schedule.user_id != user_id:
        return None
    spec = validate_spec(spec, policy)
    schedule.tz, schedule.local_time, schedule.days = spec.tz, spec.local_time, spec.days
    schedule.tone, schedule.max_duration_seconds = spec.tone, spec.max_duration_seconds
    schedule.consent_ver, schedule.enabled = spec.consent_ver, spec.enabled
    await store.save(schedule)
    # Occurrences created under the old time or days must not ring: the scheduler re-plans.
    await store.cancel_future_occurrences(schedule_id)
    return schedule


async def set_enabled(
    store: AccountabilityStore, user_id: uuid.UUID, schedule_id: uuid.UUID, enabled: bool
) -> CallSchedule | None:
    schedule = await store.get_schedule(schedule_id)
    if schedule is None or schedule.user_id != user_id:
        return None
    schedule.enabled = enabled
    await store.save(schedule)
    if not enabled:
        await store.cancel_future_occurrences(schedule_id)
    return schedule


async def delete_schedule(
    store: AccountabilityStore, user_id: uuid.UUID, schedule_id: uuid.UUID
) -> bool:
    schedule = await store.get_schedule(schedule_id)
    if schedule is None or schedule.user_id != user_id:
        return False
    await store.cancel_future_occurrences(schedule_id)
    await store.delete_schedule(schedule_id)
    return True


async def materialize_occurrences(
    store: AccountabilityStore,
    now: datetime | None = None,
    *,
    horizon: timedelta = timedelta(hours=6),
    late_grace: timedelta = timedelta(minutes=20),
) -> int:
    """Create the occurrences due in `[now - late_grace, now + horizon]`; returns how many are new.

    Safe to run on any cadence, from several workers, or twice for the same minute: the unique
    `(schedule_id, local_date)` key makes creation idempotent. Cancelled occurrences are kept (so
    an edit does not resurrect today's call at a stale time) but a re-planned time on the same
    local date is not duplicated either.
    """
    now = now or datetime.now(UTC)
    created = 0
    for schedule in await store.list_schedules(enabled_only=True):
        try:
            planned = plan_occurrences(
                tz=schedule.tz,
                local_time=schedule.local_time,
                days=list(schedule.days),
                now=now,
                horizon=horizon,
                late_grace=late_grace,
            )
        except ValueError:
            log.warning("scheduler.bad_schedule", schedule_id=str(schedule.id), tz=schedule.tz)
            continue
        for item in planned:
            _, is_new = await store.ensure_occurrence(
                schedule_id=schedule.id,
                user_id=schedule.user_id,
                local_date=item.local_date,
                scheduled_for=item.scheduled_for,
            )
            created += int(is_new)
    return created
