"""Provider webhook ingestion: verify, store first, dispatch idempotently (C04)."""

from sg_core.webhooks.ingest import (
    Dispatcher,
    IngestOutcome,
    IngestResult,
    ingest_webhook,
    mark_event,
)
from sg_core.webhooks.verifiers import (
    ElevenLabsVerifier,
    ParsedEvent,
    SignatureError,
    UnknownProviderError,
    VerifierRegistry,
    WebhookVerifier,
    default_registry,
)

__all__ = [
    "Dispatcher",
    "ElevenLabsVerifier",
    "IngestOutcome",
    "IngestResult",
    "ParsedEvent",
    "SignatureError",
    "UnknownProviderError",
    "VerifierRegistry",
    "WebhookVerifier",
    "default_registry",
    "ingest_webhook",
    "mark_event",
]
