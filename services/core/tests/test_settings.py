import pytest

from sg_core.settings import normalize_database_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgres://u:p@host:38964/tsdb?sslmode=require",
            "postgresql+asyncpg://u:p@host:38964/tsdb?ssl=require",
        ),
        ("postgresql://u:p@host/db", "postgresql+asyncpg://u:p@host/db"),
        (
            "postgresql+asyncpg://u:p@host/db?ssl=require",
            "postgresql+asyncpg://u:p@host/db?ssl=require",
        ),
    ],
)
def test_normalize_database_url(raw: str, expected: str) -> None:
    assert normalize_database_url(raw) == expected


def test_admin_owner_emails_parses_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    from sg_core.settings import Settings

    monkeypatch.setenv("ADMIN_OWNER_EMAILS", " Owner@Example.com, second@example.com ,")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.admin_owner_emails == ["owner@example.com", "second@example.com"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://a.example, https://b.example/ ,", ["https://a.example", "https://b.example"]),
        ('["https://a.example"]', ["https://a.example"]),
    ],
)
def test_cors_origins_accepts_csv_or_json(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
) -> None:
    from sg_core.settings import Settings

    monkeypatch.setenv("CORS_ORIGINS", raw)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.cors_origins == expected
