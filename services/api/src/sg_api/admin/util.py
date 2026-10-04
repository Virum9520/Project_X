"""Small pure helpers for the owner console: masking, projection, money rounding."""

from datetime import UTC, datetime
from decimal import Decimal


def mask_email(email: str | None) -> str:
    """`ada@example.com` -> `a**@example.com`. Analytics views show the least PII they can."""
    if not email or "@" not in email:
        return "unknown"
    local, _, domain = email.rpartition("@")
    return f"{local[:1]}{'*' * min(max(len(local) - 1, 2), 6)}@{domain}"


def mask_phone(number: str | None) -> str | None:
    if not number:
        return None
    return f"{'*' * max(len(number) - 4, 0)}{number[-4:]}"


def usd(value: Decimal | float | int | None) -> float:
    return round(float(value or 0), 6)


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """UTC start of this month and start of next month."""
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    nxt = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=UTC)
    return start, nxt


def project_month_end(spend_to_date: float, now: datetime) -> float:
    """Linear run-rate: spend so far scaled to the whole month.

    Uses elapsed fractional days, so it is stable within a day. During the first hour of the
    month the run rate is meaningless, so it returns the spend so far.
    """
    start, nxt = month_bounds(now)
    total = (nxt - start).total_seconds()
    elapsed = (now - start).total_seconds()
    if elapsed < 3600:
        return round(spend_to_date, 6)
    return round(spend_to_date * total / elapsed, 6)


def escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
