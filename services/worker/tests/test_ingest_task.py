"""The ingestion workflow is registered and wired to the pipeline (no Hatchet engine needed)."""

import uuid
from typing import Any

import pytest

from sg_core.knowledge import IngestResult
from sg_core.models.enums import DocumentVersionStatus
from sg_worker import tasks
from sg_worker.dispatch import DOCUMENT_INGEST_KEY, HatchetIngestDispatcher


def test_workflow_is_registered_on_the_ingest_event() -> None:
    assert tasks.ingest_document in tasks.ALL_WORKFLOWS
    assert tasks.ingest_document.name == "knowledge.ingest_document"
    assert DOCUMENT_INGEST_KEY in tasks.ingest_document.config.on_events


async def test_task_runs_the_pipeline_for_the_version(monkeypatch: pytest.MonkeyPatch) -> None:
    version_id = uuid.uuid4()
    seen: list[uuid.UUID] = []

    async def fake_job(sessionmaker: Any, store: Any, vid: uuid.UUID, **_: Any) -> IngestResult:
        seen.append(vid)
        return IngestResult(vid, DocumentVersionStatus.ACTIVE, chunks=3, mappings=2)

    monkeypatch.setattr(tasks, "run_ingestion_job", fake_job)
    monkeypatch.setattr(tasks, "object_store_from_settings", lambda: object())
    output = await tasks.ingest_document.aio_mock_run(
        tasks.IngestDocumentInput(document_version_id=version_id, request_id="r1")
    )
    assert seen == [version_id]
    assert output.status == "active" and output.chunks == 3 and output.mappings == 2


async def test_dispatcher_pushes_a_fresh_request_id_each_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pushed: list[tuple[str, dict[str, str]]] = []

    class Events:
        async def aio_push(self, key: str, payload: dict[str, str]) -> None:
            pushed.append((key, payload))

    class FakeHatchet:
        event = Events()

    monkeypatch.setattr("sg_worker.dispatch.get_hatchet", lambda: FakeHatchet())
    version_id = uuid.uuid4()
    dispatcher = HatchetIngestDispatcher()
    await dispatcher.dispatch(version_id)
    await dispatcher.dispatch(version_id)
    assert [k for k, _ in pushed] == [DOCUMENT_INGEST_KEY] * 2
    assert all(p["document_version_id"] == str(version_id) for _, p in pushed)
    assert pushed[0][1]["request_id"] != pushed[1][1]["request_id"]
