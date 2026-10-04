"""Judge calibration (C23B): a human-labeled answer set and the disagreement rate against it.

The labeled set (`labeled_set_v1.json`) is SYNTHETIC until real, consented answers are graded by
independent humans; the file says so and every report carries the flag. The runner feeds each
item to the real rubric judge as a tiny transcript, compares the judge's outcome (and assistance)
for the labeled concept and dimension with the human label, and writes a report that the owner
console Quality page shows. `python -m sg_core.evidence.calibration --help`.
"""

import asyncio
import json
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sg_core.evidence.judge import Judge, JudgeRequest
from sg_core.evidence.types import ConceptInfo, RawVerdict, RubricInfo, Transcript, Turn

LABELED_SET_PATH = Path(__file__).with_name("labeled_set_v1.json")
REPORT_PATH = Path(__file__).with_name("report_latest.json")
NO_VERDICT = "no_verdict"
OUTCOMES = ("demonstrated", "partial", "not_demonstrated", "unassessable")
# Demonstrated vs not demonstrated flips what the garden does, so these count as severe.
SEVERE = {("demonstrated", "not_demonstrated"), ("not_demonstrated", "demonstrated")}


@dataclass(frozen=True, slots=True)
class LabeledItem:
    id: str
    concept: str
    dimension: str
    turns: tuple[Turn, ...]
    human_outcome: str
    human_assistance: str


@dataclass(frozen=True, slots=True)
class LabeledSet:
    set_version: str
    synthetic: bool
    notice: str
    items: tuple[LabeledItem, ...]


def load_labeled_set(path: Path = LABELED_SET_PATH) -> LabeledSet:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items: list[LabeledItem] = []
    seen: set[str] = set()
    for it in raw["items"]:
        if it["id"] in seen:
            raise ValueError(f"duplicate calibration item id {it['id']}")
        seen.add(it["id"])
        if it["human_outcome"] not in OUTCOMES:
            raise ValueError(f"{it['id']}: bad human_outcome {it['human_outcome']!r}")
        turns = tuple(
            Turn(index=i, role=t["role"], text=t["text"]) for i, t in enumerate(it["turns"])
        )
        items.append(
            LabeledItem(
                id=it["id"],
                concept=it["concept"],
                dimension=it["dimension"],
                turns=turns,
                human_outcome=it["human_outcome"],
                human_assistance=it["human_assistance"],
            )
        )
    return LabeledSet(
        raw["set_version"], bool(raw.get("synthetic", True)), raw["notice"], tuple(items)
    )


def concept_catalog() -> dict[str, ConceptInfo]:
    """Concepts with their rubrics from the cs-core curriculum (no database needed)."""
    from sg_core.curriculum import curriculum_path, load_curriculum

    spec = load_curriculum(curriculum_path("cs-core", "v1"))
    return {
        c.key: ConceptInfo(
            id=uuid.uuid5(uuid.NAMESPACE_DNS, c.key),
            key=c.key,
            title=c.title,
            domain=c.domain,
            summary=c.summary,
            rubric=RubricInfo(None, spec.rubric_version, c.rubric.model_dump(mode="json")),
        )
        for c in spec.concepts
    }


def pick_verdict(verdicts: Sequence[RawVerdict], item: LabeledItem) -> RawVerdict | None:
    for v in verdicts:
        if v.concept_key == item.concept and v.dimension == item.dimension:
            return v
    return None


def compute_report(
    labeled: LabeledSet,
    judged: dict[str, RawVerdict | None],
    *,
    judge_model: str,
    judge_version: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Pure: the disagreement rate and breakdowns from judge verdicts keyed by item id."""
    disagreements: list[dict[str, str]] = []
    confusion: Counter[tuple[str, str]] = Counter()
    by_dim: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    severe = assist_mismatch = 0
    for item in labeled.items:
        v = judged.get(item.id)
        got = v.outcome if v else NO_VERDICT
        confusion[(item.human_outcome, got)] += 1
        wrong = got != item.human_outcome
        by_dim[item.dimension][0] += 1
        by_dim[item.dimension][1] += int(wrong)
        if wrong:
            disagreements.append(
                {
                    "id": item.id,
                    "concept": item.concept,
                    "dimension": item.dimension,
                    "human": item.human_outcome,
                    "judge": got,
                }
            )
        if (item.human_outcome, got) in SEVERE:
            severe += 1
        if v and v.assistance != item.human_assistance:
            assist_mismatch += 1
    n = len(labeled.items)
    return {
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "set_version": labeled.set_version,
        "synthetic": labeled.synthetic,
        "notice": labeled.notice,
        "judge_model": judge_model,
        "judge_version": judge_version,
        "items": n,
        "disagreements": len(disagreements),
        "disagreement_rate": round(len(disagreements) / n, 4) if n else None,
        "severe_disagreements": severe,
        "assistance_mismatches": assist_mismatch,
        "by_dimension": {
            d: {"items": c[0], "disagreements": c[1]} for d, c in sorted(by_dim.items())
        },
        "confusion": [
            {"human": h, "judge": j, "count": c} for (h, j), c in sorted(confusion.items())
        ],
        "disagreement_items": disagreements,
    }


async def run_calibration(
    judge: Judge,
    labeled: LabeledSet | None = None,
    *,
    concurrency: int = 4,
    judge_version: str = "judge@1",
) -> dict[str, Any]:
    """Judge every labeled item (each as its own tiny transcript) and compute the report."""
    labeled = labeled or load_labeled_set()
    catalog = concept_catalog()
    sem = asyncio.Semaphore(concurrency)

    async def one(item: LabeledItem) -> tuple[str, RawVerdict | None]:
        transcript = Transcript(conversation_id=f"calibration:{item.id}", turns=item.turns)
        async with sem:
            verdicts = await judge.judge(JudgeRequest(transcript, [catalog[item.concept]]))
        return item.id, pick_verdict(verdicts, item)

    judged = dict(await asyncio.gather(*(one(i) for i in labeled.items)))
    return compute_report(labeled, judged, judge_model=judge.model, judge_version=judge_version)


def save_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def load_report(path: Path = REPORT_PATH) -> dict[str, Any] | None:
    """The latest saved run, or None if no run has been recorded or the file is unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
