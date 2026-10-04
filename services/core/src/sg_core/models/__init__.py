"""SQLAlchemy models for every core table. Importing this package registers all of them on
`Base.metadata`, which Alembic autogenerate compares against."""

from sg_core.models.accountability import (
    CallAttempt,
    CallOccurrence,
    CallSchedule,
    Commitment,
    VoiceConsent,
)
from sg_core.models.base import EMBEDDING_DIM, Base
from sg_core.models.curriculum import Concept, ConceptEdge, Curriculum, Rubric
from sg_core.models.economics import (
    BudgetReservation,
    CostEntry,
    PricingVersion,
    SharedAllocation,
    UsageEvent,
)
from sg_core.models.evidence import (
    Assessment,
    AssessmentDispute,
    EvidenceItem,
    GardenRevision,
    PlantState,
)
from sg_core.models.identity import (
    AdminRoleGrant,
    AdminUser,
    AuditLog,
    Capability,
    Profile,
    RoleCapability,
    User,
)
from sg_core.models.knowledge import Chunk, ConceptMapping, Document, DocumentVersion
from sg_core.models.memory import Memory
from sg_core.models.sessions import (
    CodeSnapshot,
    HintGiven,
    ProviderEvent,
    SandboxRun,
    Session,
    SessionEvent,
)

# Tables converted to TimescaleDB hypertables: name -> (time column, chunk interval).
HYPERTABLES: dict[str, tuple[str, str]] = {
    "session_events": ("occurred_at", "7 days"),
    "usage_events": ("occurred_at", "7 days"),
}

__all__ = [
    "EMBEDDING_DIM",
    "HYPERTABLES",
    "AdminRoleGrant",
    "AdminUser",
    "Assessment",
    "AssessmentDispute",
    "AuditLog",
    "Base",
    "BudgetReservation",
    "CallAttempt",
    "CallOccurrence",
    "CallSchedule",
    "Capability",
    "Chunk",
    "CodeSnapshot",
    "Commitment",
    "Concept",
    "ConceptEdge",
    "ConceptMapping",
    "CostEntry",
    "Curriculum",
    "Document",
    "DocumentVersion",
    "EvidenceItem",
    "GardenRevision",
    "HintGiven",
    "Memory",
    "PlantState",
    "PricingVersion",
    "Profile",
    "ProviderEvent",
    "RoleCapability",
    "Rubric",
    "SandboxRun",
    "Session",
    "SessionEvent",
    "SharedAllocation",
    "UsageEvent",
    "User",
    "VoiceConsent",
]
