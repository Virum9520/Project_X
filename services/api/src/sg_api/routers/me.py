"""The signed-in user's own identity, as the API sees it."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sg_api.auth.deps import IdentityDep, SessionDep, capabilities_of, load_user, sync_user
from sg_core.identity import Capability
from sg_core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["identity"])


class Me(BaseModel):
    user_id: str
    email: str | None
    mfa_enabled: bool
    console_access: bool
    capabilities: list[Capability]


@router.get("/me", response_model=Me)
async def me(identity: IdentityDep, claims: SessionDep) -> Me:
    user = await load_user(identity, claims.user_id)
    # Mirrors `publicMetadata.onboarding` into `profiles` (Clerk remains the source of truth).
    await sync_user(identity, user)
    try:
        _, capabilities = await capabilities_of(identity, user)
    except HTTPException:  # grant store down: admin routes deny, but learners still get /v1/me
        log.warning("me.capabilities_unavailable", user_id=user.id)
        capabilities = frozenset()
    return Me(
        user_id=user.id,
        email=user.primary_email,
        mfa_enabled=user.two_factor_enabled,
        console_access=Capability.CONSOLE_ACCESS in capabilities,
        capabilities=sorted(capabilities),
    )
