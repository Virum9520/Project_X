"""Who is starting the session: the signed-in Clerk learner (C01).

Local and test environments may instead pass `X-Dev-User-Id` / `X-Dev-User-Name` when no bearer
token is sent, so voice sessions can be exercised without a Clerk app. Elsewhere a Clerk session
is required.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from sg_api.auth.deps import IdentityDep, current_session
from sg_core.settings import Settings, get_settings


class Learner(BaseModel):
    user_id: str
    # TODO(profiles): use the learner's preferred name once profiles are exposed.
    display_name: str = "there"
    timezone: str = "America/New_York"


async def current_learner(
    request: Request,
    identity: IdentityDep,
    settings: Annotated[Settings, Depends(get_settings)],
    dev_user_id: Annotated[str | None, Header(alias="X-Dev-User-Id")] = None,
    dev_user_name: Annotated[str | None, Header(alias="X-Dev-User-Name")] = None,
) -> Learner:
    if request.headers.get("Authorization"):
        claims = await current_session(request, identity)
        return Learner(user_id=claims.user_id)
    if dev_user_id and settings.dev_identity_allowed:
        return Learner(user_id=dev_user_id, display_name=dev_user_name or "there")
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "missing bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )
