"""Owner-console API. Every route needs an admin session; mutations also pass the CSRF guard and
are audited by `AuditMiddleware`."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from sg_api.auth.deps import AdminPrincipal, admin_origin_guard, require_capability
from sg_core.identity import Capability

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin"],
    dependencies=[
        Depends(admin_origin_guard),
        Depends(require_capability(Capability.CONSOLE_ACCESS)),
    ],
)

ConsoleAdmin = Annotated[AdminPrincipal, Depends(require_capability(Capability.CONSOLE_ACCESS))]


class AdminMe(BaseModel):
    user_id: str
    email: str
    is_owner: bool
    mfa_verified: bool
    capabilities: list[Capability]


@router.get("/me", response_model=AdminMe)
async def admin_me(principal: ConsoleAdmin) -> AdminMe:
    return AdminMe(
        user_id=principal.user_id,
        email=principal.email,
        is_owner=principal.is_owner,
        mfa_verified=principal.claims.second_factor_verified,
        capabilities=sorted(principal.capabilities),
    )
