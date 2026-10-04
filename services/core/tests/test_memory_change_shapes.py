"""`change_after` reads both `garden_revisions.changes` shapes, so time travel works with the
rules engine's output as well as the documented one."""

import uuid

from sg_core.memory.projections import change_after

CID = uuid.UUID(int=7)


def test_documented_shape() -> None:
    change = {"concept_id": str(CID), "after": {"status": "independent", "dimension_scores": {}}}
    assert change_after(change, {}) == (CID, {"status": "independent", "dimension_scores": {}})


def test_rules_engine_shape_resolves_concept_by_key() -> None:
    change = {
        "concept": "dsa.bfs",
        "status": {"before": "unassessed", "after": "sprouting"},
        "scores": {"before": None, "after": {"explanation": {"independent": 0.6}}},
    }
    assert change_after(change, {"dsa.bfs": CID}) == (
        CID,
        {"status": "sprouting", "dimension_scores": {"explanation": {"independent": 0.6}}},
    )


def test_unusable_changes_are_skipped() -> None:
    assert change_after({"concept": "unknown.key", "status": {"after": "x"}}, {}) is None
    assert change_after({"concept_id": "not-a-uuid", "after": {}}, {}) is None
    assert change_after({"concept_id": str(CID)}, {}) is None
    assert change_after({}, {}) is None
