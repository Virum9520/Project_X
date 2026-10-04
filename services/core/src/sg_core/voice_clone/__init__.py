"""Future-Self voice (C19): consent checked with Scribe, Instant Voice Clone, revoke."""

from sg_core.voice_clone.phrase import (
    CONSENT_STATEMENTS,
    CONSENT_VERSION,
    Challenge,
    ChallengeError,
    PhraseMatch,
    issue_challenge,
    match_phrase,
    open_challenge,
)
from sg_core.voice_clone.service import (
    AlreadyConsented,
    ConsentOutcome,
    ConsentRequired,
    FutureSelfMessage,
    FutureSelfVoice,
    InvalidChallenge,
    InvalidRecording,
    ProviderUnavailable,
    VoiceCloneError,
    sanitize_script,
)
from sg_core.voice_clone.store import (
    ConsentRecord,
    ConsentStore,
    DbConsentStore,
    InMemoryConsentStore,
)

__all__ = [
    "CONSENT_STATEMENTS",
    "CONSENT_VERSION",
    "AlreadyConsented",
    "Challenge",
    "ChallengeError",
    "ConsentOutcome",
    "ConsentRecord",
    "ConsentRequired",
    "ConsentStore",
    "DbConsentStore",
    "FutureSelfMessage",
    "FutureSelfVoice",
    "InMemoryConsentStore",
    "InvalidChallenge",
    "InvalidRecording",
    "PhraseMatch",
    "ProviderUnavailable",
    "VoiceCloneError",
    "issue_challenge",
    "match_phrase",
    "open_challenge",
    "sanitize_script",
]
