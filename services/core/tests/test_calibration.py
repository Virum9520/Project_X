"""Judge calibration: the labeled set is sound and the disagreement rate is computed correctly."""

from pathlib import Path

from sg_core.evidence.calibration import (
    LabeledItem,
    compute_report,
    concept_catalog,
    load_labeled_set,
    load_report,
    pick_verdict,
    run_calibration,
    save_report,
)
from sg_core.evidence.judge import JudgeRequest
from sg_core.evidence.types import RawVerdict


def raw(item: LabeledItem, outcome: str, assistance: str | None = None) -> RawVerdict:
    return RawVerdict(
        concept_key=item.concept,
        dimension=item.dimension,
        outcome=outcome,
        assistance=assistance or item.human_assistance,
        citations=(),
        rationale="",
    )


def test_labeled_set_is_marked_synthetic_and_valid() -> None:
    labeled = load_labeled_set()
    assert labeled.synthetic and "SYNTHETIC" in labeled.notice
    assert len(labeled.items) >= 30
    assert {i.concept for i in labeled.items} <= concept_catalog().keys()
    outcomes = {i.human_outcome for i in labeled.items}
    assert {"demonstrated", "partial", "not_demonstrated", "unassessable"} <= outcomes
    for item in labeled.items:
        assert item.turns[-1].role == "learner" and item.turns[0].role == "agent"


def test_report_counts_disagreements_and_severe_flips() -> None:
    labeled = load_labeled_set()
    judged: dict[str, RawVerdict | None] = {i.id: raw(i, i.human_outcome) for i in labeled.items}
    perfect = compute_report(labeled, judged, judge_model="m", judge_version="v")
    assert perfect["disagreement_rate"] == 0.0 and perfect["severe_disagreements"] == 0

    demo = next(i for i in labeled.items if i.human_outcome == "demonstrated")
    part = next(i for i in labeled.items if i.human_outcome == "partial")
    judged[demo.id] = raw(demo, "not_demonstrated")  # severe
    judged[part.id] = None  # judge gave nothing for it
    report = compute_report(labeled, judged, judge_model="m", judge_version="v")
    assert report["disagreements"] == 2
    assert report["severe_disagreements"] == 1
    assert report["disagreement_rate"] == round(2 / len(labeled.items), 4)
    assert {d["judge"] for d in report["disagreement_items"]} == {"not_demonstrated", "no_verdict"}


def test_assistance_mismatch_is_counted_separately() -> None:
    labeled = load_labeled_set()
    item = labeled.items[0]
    judged: dict[str, RawVerdict | None] = {i.id: raw(i, i.human_outcome) for i in labeled.items}
    judged[item.id] = raw(item, item.human_outcome, "assisted")
    report = compute_report(labeled, judged, judge_model="m", judge_version="v")
    assert report["assistance_mismatches"] == 1 and report["disagreements"] == 0


class OracleJudge:
    """Agrees with the human label except on every tenth item. Finds the item by its answer."""

    model = "oracle"

    def __init__(self) -> None:
        self.by_text = {i.turns[-1].text: i for i in load_labeled_set().items}

    async def judge(self, request: JudgeRequest) -> list[RawVerdict]:
        item = self.by_text[request.transcript.turns[-1].text]
        outcome = item.human_outcome
        if int(item.id[-3:]) % 10 == 0:
            outcome = "partial" if outcome != "partial" else "demonstrated"
        return [raw(item, outcome)]


async def test_run_calibration_end_to_end(tmp_path: Path) -> None:
    report = await run_calibration(OracleJudge())
    assert report["items"] == len(load_labeled_set().items)
    assert 0 < report["disagreement_rate"] < 0.2
    path = tmp_path / "r.json"
    save_report(report, path)
    assert load_report(path) == report
    assert load_report(tmp_path / "missing.json") is None


def test_pick_verdict_matches_concept_and_dimension() -> None:
    item = load_labeled_set().items[0]
    other = RawVerdict("x.y", item.dimension, "demonstrated", "independent", (), "")
    assert pick_verdict([other], item) is None
    assert pick_verdict([other, raw(item, "partial")], item) is not None
