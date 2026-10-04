"""API authentication and authorization: Clerk JWTs, owner allowlist, capabilities."""

from sg_api.auth.context import Identity, build_identity
from sg_api.auth.deps import (
    AdminPrincipal,
    admin_origin_guard,
    current_admin,
    current_session,
    record_audit,
    require_capability,
)

__all__ = [
    "AdminPrincipal",
    "Identity",
    "admin_origin_guard",
    "build_identity",
    "current_admin",
    "current_session",
    "record_audit",
    "require_capability",
]
