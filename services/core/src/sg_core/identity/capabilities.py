"""Capability-based permissions for the owner console and gateway.

Admin endpoints check a capability, never a role name. Owners in `ADMIN_OWNER_EMAILS` hold every
capability; anyone else gets only what `admin_role_grants` gives them. Keep this list in sync with
`CAPABILITIES` in `packages/contracts/src/identity.ts`.
"""

from enum import StrEnum


class Capability(StrEnum):
    CONSOLE_ACCESS = "console.access"
    USERS_READ = "users.read"
    USERS_WRITE = "users.write"
    USAGE_READ = "usage.read"
    CALLS_READ = "calls.read"
    CALLS_TRIGGER = "calls.trigger"
    QUALITY_READ = "quality.read"
    ASSISTANT_USE = "assistant.use"
    AUDIT_READ = "audit.read"
    GRANTS_MANAGE = "grants.manage"


OWNER_CAPABILITIES: frozenset[Capability] = frozenset(Capability)
