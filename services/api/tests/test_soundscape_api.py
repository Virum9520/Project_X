import pytest
from httpx import ASGITransport, AsyncClient

from sg_api.main import create_app
from sg_api.soundscape.router import get_object_store
from sg_core.providers.elevenlabs import AudioResult
from sg_core.providers.storage import InMemoryObjectStore
from sg_core.settings import Environment, Settings, get_settings
from sg_core.soundscape import all_specs, generate_assets

SETTINGS = Settings(_env_file=None, environment=Environment.TEST)  # type: ignore[call-arg]
DEV = {"X-Dev-User-Id": "learner_1"}


class Client:
    async def compose_music(self, prompt, *, length_ms, model_id="x", usage=None):  # type: ignore[no-untyped-def]
        return AudioResult(audio=b"m")

    async def generate_sound_effect(self, text, **kw):  # type: ignore[no-untyped-def]
        return AudioResult(audio=b"s")


class NoHold:
    def __call__(self, amount):  # type: ignore[no-untyped-def]
        class H:
            actual_usd = None

            async def __aenter__(self) -> "H":
                return self

            async def __aexit__(self, *a: object) -> None:
                return None

        return H()


@pytest.fixture
async def parts():  # type: ignore[no-untyped-def]
    store = InMemoryObjectStore()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    app.dependency_overrides[get_object_store] = lambda: store
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, store


async def test_manifest_404_until_generated_then_lists_signed_urls(parts) -> None:  # type: ignore[no-untyped-def]
    client, store = parts
    assert (await client.get("/v1/soundscape/manifest")).status_code == 401
    assert (await client.get("/v1/soundscape/manifest", headers=DEV)).status_code == 404
    await generate_assets(Client(), store, all_specs(), hold=NoHold())  # type: ignore[arg-type]
    res = await client.get("/v1/soundscape/manifest", headers=DEV)
    body = res.json()
    assert res.status_code == 200 and body["version"] == 1
    ids = {a["id"] for a in body["assets"]}
    assert {"music.thriving.summer", "sfx.growth"} <= ids
    assert all(a["url"].startswith("memory://audio/v1/") for a in body["assets"])
    stem = next(a for a in body["assets"] if a["id"] == "music.wilting.winter")
    assert stem["loop"] and stem["mood"] == "wilting" and stem["season"] == "winter"
