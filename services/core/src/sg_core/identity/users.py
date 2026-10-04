"""Mirroring Clerk users (and their onboarding answers) into our own tables."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sg_core.identity.clerk import ClerkUser

EXPERIENCE_LEVELS = frozenset(
    {"starting-out", "coursework", "projects", "internship", "professional"}
)


class UserStore(Protocol):
    async def sync(self, user: ClerkUser) -> None:
        """Upsert the `users` row, and the `profiles` row once onboarding is complete."""
        ...


class NullUserStore:
    """For tests and local runs without a database."""

    async def sync(self, user: ClerkUser) -> None:
        return None


@dataclass(frozen=True, slots=True)
class OnboardingFields:
    major: str | None
    goals: list[str]
    experience_level: str | None
    timezone: str | None
    onboarded_at: datetime | None


def parse_onboarding(raw: dict[str, Any] | None) -> OnboardingFields | None:
    """Map Clerk `publicMetadata.onboarding` (see `OnboardingProfile` in the contracts) to columns.

    The web app validates before writing, but metadata is still data: coerce defensively and drop
    anything malformed instead of failing the request.
    """
    if not raw:
        return None
    major = raw.get("major")
    experience = raw.get("experience")
    timezone = raw.get("timezone")
    goals = raw.get("goals")
    return OnboardingFields(
        major=major.strip()[:200] if isinstance(major, str) and major.strip() else None,
        goals=[g for g in goals if isinstance(g, str)][:20] if isinstance(goals, list) else [],
        experience_level=experience if experience in EXPERIENCE_LEVELS else None,
        timezone=timezone[:64] if isinstance(timezone, str) and timezone else None,
        onboarded_at=_parse_time(raw.get("completedAt")),
    )


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
