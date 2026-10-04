"""Pure scheduling maths: IANA timezones, local times, DST and quiet hours.

DST rules (the build plan's): a local time that does not exist on a date (spring forward) is
skipped for that date; a local time that happens twice (fall back) runs once, at its first
occurrence. "Once" is also enforced by the unique `(schedule_id, local_date)` occurrence key.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def load_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError(f"unknown IANA timezone: {name!r}") from exc


def parse_hhmm(value: str) -> time:
    try:
        hours, minutes = value.split(":")
        return time(int(hours), int(minutes))
    except ValueError as exc:
        raise ValueError(f"expected HH:MM, got {value!r}") from exc


def occurrence_instant(local_date: date, local_time: time, tz: str) -> datetime | None:
    """The UTC instant of `local_time` on `local_date` in `tz`, or None if it does not exist."""
    zone = load_zone(tz)
    naive = datetime.combine(local_date, local_time.replace(tzinfo=None))
    first = naive.replace(tzinfo=zone, fold=0)
    instant = first.astimezone(UTC)
    if instant.astimezone(zone).replace(tzinfo=None) != naive:
        return None  # inside a spring-forward gap
    return instant  # fold=0: the earlier of two ambiguous instants


def local_date_of(instant: datetime, tz: str) -> date:
    return instant.astimezone(load_zone(tz)).date()


def in_quiet_hours(instant: datetime, tz: str, start: time, end: time) -> bool:
    """True if the local time at `instant` is in `[start, end)`; the window may wrap midnight."""
    local = instant.astimezone(load_zone(tz)).time().replace(tzinfo=None)
    if start == end:
        return False
    if start < end:
        return start <= local < end
    return local >= start or local < end


@dataclass(frozen=True, slots=True)
class PlannedOccurrence:
    local_date: date
    scheduled_for: datetime  # UTC


def plan_occurrences(
    *,
    tz: str,
    local_time: time,
    days: list[int],
    now: datetime,
    horizon: timedelta,
    late_grace: timedelta = timedelta(0),
) -> list[PlannedOccurrence]:
    """Occurrences whose instant lies in `[now - late_grace, now + horizon]`, oldest first.

    `days` are ISO weekdays (1=Mon..7=Sun) on the *local* date. Covering a late-grace window lets
    a restarted scheduler recover a call that should have been created during an outage; the
    unique occurrence key makes repeated planning harmless.
    """
    zone = load_zone(tz)
    lo, hi = now - late_grace, now + horizon
    first = lo.astimezone(zone).date() - timedelta(days=1)
    last = hi.astimezone(zone).date() + timedelta(days=1)
    planned: list[PlannedOccurrence] = []
    day = first
    while day <= last:
        if day.isoweekday() in days:
            instant = occurrence_instant(day, local_time, tz)
            if instant is not None and lo <= instant <= hi:
                planned.append(PlannedOccurrence(day, instant))
        day += timedelta(days=1)
    return planned
