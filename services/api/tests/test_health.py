from httpx import ASGITransport, AsyncClient

from sg_api.main import create_app


async def test_healthz_returns_ok_and_request_id() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert len(response.headers["X-Request-ID"]) == 32


async def test_inbound_request_id_is_preserved_when_well_formed() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/healthz", headers={"X-Request-ID": "abc-123-def"})
    assert response.headers["X-Request-ID"] == "abc-123-def"


async def test_malformed_request_id_is_replaced() -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/healthz", headers={"X-Request-ID": "bad id with spaces!"})
    assert response.headers["X-Request-ID"] != "bad id with spaces!"
