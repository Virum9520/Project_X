import asyncio
from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient

from sg_api.main import create_app
from sg_api.routers import health
from sg_core import db, redis_client
from sg_core.settings import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("REDIS_URL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _ok() -> bool:
    return True


async def _boom() -> bool:
    raise ConnectionError("unreachable")


async def _get(path: str) -> tuple[int, dict[str, object]]:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        response = await c.get(path)
    return response.status_code, response.json()


async def test_ready_without_redis_checks_only_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "ping", _ok)
    code, body = await _get("/readyz")
    assert code == 200
    assert body == {"status": "ready", "checks": {"database": True}}


async def test_redis_is_checked_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://example:6379/0")
    monkeypatch.setattr(db, "ping", _ok)
    monkeypatch.setattr(redis_client, "ping", _boom)
    code, body = await _get("/readyz")
    assert code == 503
    assert body == {"status": "degraded", "checks": {"database": True, "redis": False}}


async def test_hanging_check_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _hang() -> bool:
        await asyncio.sleep(10)
        return True

    monkeypatch.setattr(db, "ping", _hang)
    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.05)
    code, body = await _get("/readyz")
    assert code == 503
    assert body["checks"] == {"database": False}


async def test_healthz_reports_railway_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123")
    code, body = await _get("/healthz")
    assert code == 200
    assert body["commit"] == "abc123"


async def test_cors_allows_preview_origin_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("CORS_ORIGIN_REGEX", r"https://sg-web-[a-z0-9-]+-team\.vercel\.app")
    app = create_app()
    preflight = {"Access-Control-Request-Method": "GET"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        exact = await c.options(
            "/healthz", headers={**preflight, "Origin": "https://app.example.com"}
        )
        preview = await c.options(
            "/healthz", headers={**preflight, "Origin": "https://sg-web-git-x-team.vercel.app"}
        )
        other = await c.options("/healthz", headers={**preflight, "Origin": "https://evil.example"})
    assert exact.headers["access-control-allow-origin"] == "https://app.example.com"
    assert preview.headers["access-control-allow-origin"] == "https://sg-web-git-x-team.vercel.app"
    assert "access-control-allow-origin" not in other.headers
