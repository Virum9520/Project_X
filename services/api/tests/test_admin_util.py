from datetime import UTC, datetime

import pytest

from sg_api.admin.util import escape_like, mask_email, mask_phone, month_bounds, project_month_end


def test_mask_email_keeps_domain_hides_local_part() -> None:
    assert mask_email("ada@example.com") == "a**@example.com"
    assert mask_email("ada.lovelace@example.com").startswith("a******@")
    assert "ada" not in mask_email("ada@example.com")
    assert mask_email(None) == "unknown"
    assert mask_email("not-an-email") == "unknown"


def test_mask_phone_keeps_last_four() -> None:
    assert mask_phone("+15555550123") == "********0123"
    assert mask_phone(None) is None


def test_month_bounds_handle_december() -> None:
    start, end = month_bounds(datetime(2026, 12, 15, 8, tzinfo=UTC))
    assert start == datetime(2026, 12, 1, tzinfo=UTC)
    assert end == datetime(2027, 1, 1, tzinfo=UTC)


def test_projection_scales_to_the_whole_month() -> None:
    # Exactly half way through a 30-day month: spend doubles.
    now = datetime(2026, 4, 16, tzinfo=UTC)
    assert project_month_end(10.0, now) == pytest.approx(10.0 * 30 / 15)


def test_projection_is_just_the_spend_in_the_first_hour() -> None:
    assert project_month_end(0.4, datetime(2026, 4, 1, 0, 30, tzinfo=UTC)) == 0.4


def test_escape_like_neutralises_wildcards() -> None:
    assert escape_like("100%_a\\") == "100\\%\\_a\\\\"


def test_call_now_targets_parse_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    from sg_core.settings import Settings

    monkeypatch.setenv("CALL_NOW_APPROVED_TARGETS", "web, +15555550123")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.call_now_approved_targets == ["web", "+15555550123"]
    assert settings.call_now_cooldown_seconds == 60
