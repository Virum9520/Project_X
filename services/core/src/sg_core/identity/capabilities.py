"""Capability-based permissions for the owner console and gateway.

Admin endpoints check a capability, never a role name. Owners in `ADMIN_OWNER_EMAILS` hold every
capability; anyone else gets only what `admin_role_grants` gives them. Keep this list in sync with
`CAPABILITIES` in `packages/contracts/src/identity.ts`.
"""

from enum import StrEnum

from sg_core.models.enums import AdminRole


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


CAPABILITY_DESCRIPTIONS: dict[Capability, str] = {
    Capability.CONSOLE_ACCESS: "Sign in to the owner console",
    Capability.USERS_READ: "View learners and their profiles",
    Capability.USERS_WRITE: "Change learner accounts and settings",
    Capability.USAGE_READ: "View usage, cost and budget dashboards",
    Capability.CALLS_READ: "View call and session history",
    Capability.CALLS_TRIGGER: "Start a call to a learner (Call now)",
    Capability.QUALITY_READ: "View judge and quality reports",
    Capability.ASSISTANT_USE: "Use the owner assistant",
    Capability.AUDIT_READ: "Read the audit log",
    Capability.GRANTS_MANAGE: "Invite admins and change their roles",
}

_READ_ONLY = {
    Capability.CONSOLE_ACCESS,
    Capability.USAGE_READ,
    Capability.CALLS_READ,
    Capability.QUALITY_READ,
}

# Seeded into `role_capabilities`. Owners hold everything; the rest are least-privilege defaults
# that an owner can adjust in the table without a deploy (seeding never removes rows).
ROLE_CAPABILITIES: dict[AdminRole, frozenset[Capability]] = {
    AdminRole.OWNER: OWNER_CAPABILITIES,
    AdminRole.OPS_ADMIN: frozenset(
        _READ_ONLY
        | {Capability.USERS_READ, Capability.USERS_WRITE, Capability.CALLS_TRIGGER}
        | {Capability.ASSISTANT_USE}
    ),
    AdminRole.ANALYST: frozenset(_READ_ONLY | {Capability.USERS_READ}),
    AdminRole.DEVELOPER: frozenset(_READ_ONLY | {Capability.AUDIT_READ}),
}
