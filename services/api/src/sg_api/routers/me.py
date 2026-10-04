"""The signed-in user's own identity, as the API sees it."""

from fastapi import APIRouter
from pydantic import BaseModel

from sg_api.auth.deps import IdentityDep, SessionDep, capabilities_of, load_user
from sg_core.identity import Capability

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
    _, capabilities = await capabilities_of(identity, user)
    return Me(
        user_id=user.id,
        email=user.primary_email,
        mfa_enabled=user.two_factor_enabled,
        console_access=Capability.CONSOLE_ACCESS in capabilities,
        capabilities=sorted(capabilities),
    )
