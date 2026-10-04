"""`GET /v1/soundscape/manifest`: the current audio assets with short-lived download URLs.

Any signed-in learner may read it; assets are the same for everyone. When nothing has been
generated yet (the owner has not run `scripts/generate-audio`) the route answers 404 and the
browser engine stays silent, which is a supported state.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from sg_api.sessions.identity import Learner, current_learner
from sg_core.providers.base import ProviderNotConfiguredError
from sg_core.providers.storage import ObjectStore, object_store_from_settings
from sg_core.soundscape import load_manifest

router = APIRouter(prefix="/v1/soundscape", tags=["soundscape"])

URL_TTL_SECONDS = 3600


class SoundAssetOut(BaseModel):
    id: str
    kind: str
    url: str
    mood: str | None = None
    season: str | None = None
    loop: bool = False
    duration_seconds: float
    content_type: str


class SoundManifestOut(BaseModel):
    version: int
    expires_in_seconds: int
    assets: list[SoundAssetOut]


def get_object_store() -> ObjectStore:
    try:
        return object_store_from_settings()
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "audio storage not configured"
        ) from exc


@router.get("/manifest", response_model=SoundManifestOut)
async def soundscape_manifest(
    _: Annotated[Learner, Depends(current_learner)],
    store: Annotated[ObjectStore, Depends(get_object_store)],
    response: Response,
) -> SoundManifestOut:
    manifest: dict[str, Any] | None = await load_manifest(store)
    if manifest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no soundscape has been generated yet")
    response.headers["Cache-Control"] = "private, max-age=600"
    return SoundManifestOut(
        version=manifest["version"],
        expires_in_seconds=URL_TTL_SECONDS,
        assets=[
            SoundAssetOut(
                id=a["id"],
                kind=a["kind"],
                url=await store.presigned_get_url(a["key"], expires_seconds=URL_TTL_SECONDS),
                mood=a.get("mood"),
                season=a.get("season"),
                loop=a.get("loop", False),
                duration_seconds=a["duration_seconds"],
                content_type=a["content_type"],
            )
            for a in manifest["assets"]
        ],
    )
