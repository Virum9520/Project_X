"""Domain enums persisted as checked VARCHAR columns.

`Character`, `Dimension` and the plant stages mirror `packages/contracts/src/index.ts`.
"""

from enum import StrEnum


class Character(StrEnum):
    DRONA = "drona"
    ARJUNA = "arjuna"
    VIDURA = "vidura"
    BHIMA = "bhima"
    KRISHNA = "krishna"
    SANJAYA = "sanjaya"


class Dimension(StrEnum):
    EXPLANATION = "explanation"
    APPLICATION = "application"
    TRANSFER = "transfer"
    RETENTION = "retention"


class PlantStatus(StrEnum):
    UNASSESSED = "unassessed"
    SPROUTING = "sprouting"
    ASSISTED = "assisted"
    INDEPENDENT = "independent"
    TRANSFER = "transfer"
    RETAINED = "retained"
    DUE = "due"
    WILTING = "wilting"


# ── Identity ──
class AdminRole(StrEnum):
    OWNER = "owner"
    OPS_ADMIN = "ops_admin"
    ANALYST = "analyst"
    DEVELOPER = "developer"


class AdminStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ActorType(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"
    AGENT = "agent"


# ── Curriculum ──
class CurriculumStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class ConceptEdgeKind(StrEnum):
    PREREQUISITE = "prerequisite"
    RELATED = "related"


# ── Knowledge ──
class DocumentKind(StrEnum):
    STUDY_MATERIAL = "study_material"
    RESUME = "resume"
    JOB_DESCRIPTION = "job_description"
    OTHER = "other"


class DocumentVersionStatus(StrEnum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    MAPPING = "mapping"
    EMBEDDING = "embedding"
    ACTIVE = "active"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class ReviewStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


# ── Sessions ──
class SessionStatus(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    ABANDONED = "abandoned"


class EventSource(StrEnum):
    CLIENT = "client"
    SERVER = "server"
    AGENT = "agent"
    PROVIDER = "provider"


class ProviderEventStatus(StrEnum):
    RECEIVED = "received"
    ENQUEUED = "enqueued"
    PROCESSED = "processed"
    FAILED = "failed"
    IGNORED = "ignored"


class SandboxRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    TIMEOUT = "timeout"


# ── Evidence and progression ──
class Assistance(StrEnum):
    """Assisted evidence never counts as independent evidence."""

    INDEPENDENT = "independent"
    ASSISTED = "assisted"


class AssessmentOutcome(StrEnum):
    DEMONSTRATED = "demonstrated"
    PARTIAL = "partial"
    NOT_DEMONSTRATED = "not_demonstrated"
    UNASSESSABLE = "unassessable"


class AssessmentStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"


class DisputeStatus(StrEnum):
    OPEN = "open"
    UPHELD = "upheld"
    REJECTED = "rejected"


# ── Memory ──
class MemoryLayer(StrEnum):
    PROFILE = "profile"
    KNOWLEDGE = "knowledge"
    SESSION = "session"
    SKILLS = "skills"
    COMMITMENTS = "commitments"
    PRIVATE = "private"


class MemoryStatus(StrEnum):
    PROVISIONAL = "provisional"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    DISPUTED = "disputed"


class MemorySource(StrEnum):
    USER = "user"
    AGENT = "agent"
    EVIDENCE_PIPELINE = "evidence_pipeline"
    SYSTEM = "system"


# ── Accountability ──
class CommitmentStatus(StrEnum):
    OPEN = "open"
    COMPLETED = "completed"
    MISSED = "missed"
    CANCELLED = "cancelled"


class CompletionSource(StrEnum):
    """Self-report and observed completion stay distinct."""

    SELF_REPORTED = "self_reported"
    OBSERVED = "observed"


class CallChannelKind(StrEnum):
    WEB = "web"
    PHONE = "phone"


class CallState(StrEnum):
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    DISPATCHING = "dispatching"
    RINGING = "ringing"
    CONNECTED = "connected"
    COMPLETED = "completed"
    BUSY = "busy"
    UNANSWERED = "unanswered"
    FAILED = "failed"
    CANCELLED = "cancelled"
    MISSED = "missed"
    UNKNOWN = "unknown"


# ── Economics ──
class CostCenter(StrEnum):
    LEARNER = "learner"
    DEVELOPER = "developer"
    OWNER_ASSISTANT = "owner_assistant"
    INFRASTRUCTURE = "infrastructure"


class CostKind(StrEnum):
    ESTIMATED = "estimated"
    PROVIDER = "provider"
    RECONCILED = "reconciled"


class ReservationStatus(StrEnum):
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"
    EXPIRED = "expired"
