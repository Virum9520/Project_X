"""Who is starting the session. STUB until C01 (Clerk JWKS) lands.

C01 replaces `current_learner` with real Clerk verification. Until then it only works in local
and test environments, from `X-Dev-User-Id` / `X-Dev-User-Name` headers, and fails closed
everywhere else.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel

from sg_core.settings import Environment, Settings, get_settings


class Learner(BaseModel):
    user_id: str
    display_name: str
    timezone: str = "America/New_York"


async def current_learner(
    settings: Annotated[Settings, Depends(get_settings)],
    dev_user_id: Annotated[str | None, Header(alias="X-Dev-User-Id")] = None,
    dev_user_name: Annotated[str | None, Header(alias="X-Dev-User-Name")] = None,
) -> Learner:
    if settings.environment not in (Environment.LOCAL, Environment.TEST):
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "learner authentication is not configured yet"
        )
    if not dev_user_id:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "X-Dev-User-Id header required in local/test"
        )
    return Learner(user_id=dev_user_id, display_name=dev_user_name or "there")
