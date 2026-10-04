"""Dispatching stored provider events to Hatchet (used by the API's webhook route)."""

import uuid

from sg_worker.client import get_hatchet

PROVIDER_EVENT_KEY = "provider_event.received"
DOCUMENT_INGEST_KEY = "knowledge.document.ingest_requested"


class HatchetDispatcher:
    """Pushes a Hatchet event; the `provider_event.process` workflow listens for it.

    Duplicate pushes are harmless: the workflow is idempotent on `provider_event_id` in Hatchet
    and the handler claim is guarded by a row lock in the database.
    """

    async def dispatch(self, provider_event_id: uuid.UUID, provider: str, event_type: str) -> None:
        await get_hatchet().event.aio_push(
            PROVIDER_EVENT_KEY,
            {
                "provider_event_id": str(provider_event_id),
                "provider": provider,
                "event_type": event_type,
            },
        )


class HatchetIngestDispatcher:
    """Asks the worker to ingest one document version (`knowledge.ingest_document`).

    Each push carries a fresh `request_id`, so a deliberate retry of a failed version is not
    swallowed by Hatchet's idempotency window; the pipeline itself is idempotent per version.
    """

    async def dispatch(self, document_version_id: uuid.UUID) -> None:
        await get_hatchet().event.aio_push(
            DOCUMENT_INGEST_KEY,
            {"document_version_id": str(document_version_id), "request_id": uuid.uuid4().hex},
        )
