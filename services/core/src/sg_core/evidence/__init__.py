"""Evidence and judge pipeline (C11): post-call workflow, micro-judge, validation, garden revisions.

Transcripts are data, never instructions. The judge proposes structured verdicts, `validation`
checks them, and only the deterministic rules engine (`sg_core.rules`) changes the garden.
"""

from sg_core.evidence.judge import (
    JUDGE_VERSION,
    MICRO_JUDGE_VERSION,
    ChatLLM,
    Judge,
    JudgeError,
    JudgeRequest,
    LLMJudge,
    MicroJudge,
)
from sg_core.evidence.observations import (
    ObservationInput,
    ObservationOutcome,
    ObservationRejectedError,
    record_observation,
)
from sg_core.evidence.pipeline import (
    ConversationSource,
    PipelineDeps,
    SessionNotFoundError,
    run_post_call,
)
from sg_core.evidence.store import (
    EvidenceStore,
    InMemoryEvidenceStore,
    SessionRef,
    StaleGardenError,
)
from sg_core.evidence.types import (
    AgentObservation,
    ConceptInfo,
    MicroVerdict,
    PipelineResult,
    RawVerdict,
    RubricInfo,
    Transcript,
    Verdict,
)
from sg_core.evidence.validation import ValidationContext, validate_verdicts

__all__ = [
    "JUDGE_VERSION",
    "MICRO_JUDGE_VERSION",
    "AgentObservation",
    "ChatLLM",
    "ConceptInfo",
    "ConversationSource",
    "EvidenceStore",
    "InMemoryEvidenceStore",
    "Judge",
    "JudgeError",
    "JudgeRequest",
    "LLMJudge",
    "MicroJudge",
    "MicroVerdict",
    "ObservationInput",
    "ObservationOutcome",
    "ObservationRejectedError",
    "PipelineDeps",
    "PipelineResult",
    "RawVerdict",
    "RubricInfo",
    "SessionNotFoundError",
    "SessionRef",
    "StaleGardenError",
    "Transcript",
    "ValidationContext",
    "Verdict",
    "record_observation",
    "run_post_call",
    "validate_verdicts",
]
