"""The demo seed replayed against the in-memory store (no database, no network)."""

import uuid
from datetime import UTC, datetime

import pytest
from evidence_fixtures import catalog

from sg_core.demo.script import CONVOS
from sg_core.demo.seed import (
    SeedRefusedError,
    conversation_payload,
    guard_environment,
    replay_history,
)
from sg_core.evidence import InMemoryEvidenceStore
from sg_core.models.enums import MemoryLayer, MemoryStatus, PlantStatus
from sg_core.rules import earned_stage, load_profile
from sg_core.settings import Environment, get_settings

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def _store() -> tuple[InMemoryEvidenceStore, uuid.UUID]:
    user = uuid.uuid4()
    return InMemoryEvidenceStore(catalog(), users={"demo": user}), user


async def test_history_builds_a_garden_where_every_growth_cites_evidence() -> None:
    store, user = _store()
    report = await replay_history(store, user, now=NOW)

    assert all(r.status == "judged" for _, r in report.sessions)
    plants = store.plants[user]
    # The first evidence is weeks old, so some displayed statuses are DUE or WILTING; the stage the
    # evidence earned is what the story asserts.
    profile = load_profile("normal")
    status = {k: earned_stage(p, profile) for k, p in plants.items()}
    assert status["dsa.big_o"] is PlantStatus.RETAINED
    assert status["dsa.binary_search"] is PlantStatus.TRANSFER
    assert status["dsa.hash_tables"] is PlantStatus.INDEPENDENT
    assert status["databases.indexes"] is PlantStatus.INDEPENDENT
    assert status["dsa.bfs"] is PlantStatus.SPROUTING
    assert status["dsa.dfs"] is PlantStatus.ASSISTED
    assert status["os.race_conditions"] is PlantStatus.SPROUTING
    assert status["databases.transactions_acid"] is PlantStatus.SPROUTING
    # Ambiguous and adversarial answers never grow a plant.
    assert "dsa.heaps" not in plants and "dsa.union_find" not in plants

    # Assisted evidence stays separate from independent evidence.
    bfs = plants["dsa.bfs"]
    assert bfs.dimension("application").independent == 0.0
    assert bfs.dimension("application").assisted > 0.0

    assert store.revisions, "garden revisions were written by the rules engine"
    cited = set(store.evidence)
    for rev in store.revisions:
        for change in rev["changes"]:
            for event in change["events"]:
                assert event["evidence_ids"], "growth without evidence"
                assert {uuid.UUID(i) for i in event["evidence_ids"]} <= cited
    skills = [m for m in store.memories.values() if m.new.layer is MemoryLayer.SKILLS]
    assert skills and all(m.new.evidence_ids for m in skills)


async def test_scripted_edge_cases_are_handled_by_the_real_validators() -> None:
    store, user = _store()
    report = await replay_history(store, user, now=NOW)
    by_key = dict(report.sessions)

    assert by_key["13_heaps_ambiguous"].reassess == 1
    assert by_key["14_union_find_gaming"].reassess == 1  # injection flagged, uncertainty raised
    kinds = [m.new.kind for m in store.memories.values()]
    assert kinds.count("reassess_request") == 2
    assert any(
        m.new.kind == "misconception" and m.status is MemoryStatus.PROVISIONAL
        for m in store.memories.values()
    )
    # Every scripted quote was found verbatim in a learner turn.
    assert all(not r.rejected for _, r in report.sessions)


async def test_replaying_the_history_is_idempotent() -> None:
    store, user = _store()
    await replay_history(store, user, now=NOW)
    before = (
        len(store.revisions),
        len(store.evidence),
        len(store.assessments),
        len(store.memories),
    )
    again = await replay_history(store, user, now=NOW.replace(day=20))
    assert all(r.status == "unchanged" for _, r in again.sessions)
    assert before == (
        len(store.revisions),
        len(store.evidence),
        len(store.assessments),
        len(store.memories),
    )


def test_payloads_only_cite_learner_words_and_conversation_ids_are_unique() -> None:
    ids = [c.conversation_id for c in CONVOS]
    assert len(ids) == len(set(ids))
    for convo in CONVOS:
        learner = " ".join(t.text.lower() for t in convo.turns if t.role == "learner")
        for v in convo.verdicts:
            assert " ".join(v.quote.lower().split()) in " ".join(learner.split())
        assert conversation_payload(convo, NOW)["conversation_id"] == convo.conversation_id


def test_seed_refuses_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "environment", Environment.PROD)
    with pytest.raises(SeedRefusedError):
        guard_environment(allow_dev=True)
    monkeypatch.setattr(get_settings(), "environment", Environment.DEV)
    with pytest.raises(SeedRefusedError):
        guard_environment(allow_dev=False)
    guard_environment(allow_dev=True)
