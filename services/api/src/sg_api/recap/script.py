"""The weekly Sanjaya recap script, composed from the learner's own analytics.

Pure functions over `GardenData` (no database, model or network), so every claim is checkable.
Numbers and statements come from `answer_metric`, the same source the dashboard and Ask Sanjaya
use; each segment lists the evidence ids that back it, and only ids that exist for this learner
are ever cited. Assisted evidence is never described as mastery. Stored text (summaries) is
flattened through `sanitize` and is data, never instructions; there is no model in this path.

Each segment also names the garden focus the camera should fly to while it is spoken, in the
`focusToString` form from `@sg/three` (`garden`, `grove:dsa`, `plant:dsa.graphs`).
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sg_api.garden.analytics import Query, answer_metric
from sg_api.garden.build import build_dataset
from sg_api.garden.data import GardenData
from sg_api.garden.schemas import AnalyticsOut, GardenDatasetOut
from sg_core.memory.ranking import sanitize

MAX_CONCEPT_SEGMENTS = 4
MAX_SEGMENT_CHARS = 280
WEEK_DAYS = 7
SCRIPT_VERSION = "recap-script@1"

SegmentKind = Literal["intro", "growth", "practice", "next", "outro"]


@dataclass(slots=True)
class Segment:
    id: str
    kind: SegmentKind
    text: str
    focus: str = "garden"
    concept_key: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    # Character offsets of `text` within `RecapScript.narration` (end exclusive).
    start_char: int = 0
    end_char: int = 0


@dataclass(slots=True)
class RecapScript:
    week: str  # ISO week of `week_end`, e.g. 2026-W40
    week_start: date
    week_end: date
    segments: list[Segment]
    narration: str
    rules_version: str
    quiet: bool  # no growth this week: the recap says so instead of inventing progress

    @property
    def citations(self) -> list[str]:
        return list(dict.fromkeys(i for s in self.segments for i in s.evidence_ids))


def iso_week(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def week_window(as_of: datetime) -> tuple[date, date]:
    """The seven UTC days ending on `as_of`'s date."""
    end = as_of.astimezone(UTC).date()
    return end - timedelta(days=WEEK_DAYS - 1), end


def _clip(text: str) -> str:
    return sanitize(text, MAX_SEGMENT_CHARS)


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _growth_segments(
    data: GardenData, dataset: GardenDatasetOut, changes: AnalyticsOut
) -> list[Segment]:
    titles = {p.key: p.title for p in data.view.plants}
    kind_of = {e.id: e.kind for e in dataset.evidence}
    by_plant: dict[str, list[dict[str, object]]] = {}
    for c in changes.data["changes"]:  # newest first
        by_plant.setdefault(str(c["concept_id"]), []).append(c)
    segments: list[Segment] = []
    for key, events in list(by_plant.items())[:MAX_CONCEPT_SEGMENTS]:
        latest = events[0]
        ids = [str(i) for e in events for i in e["evidence_ids"]]  # type: ignore[attr-defined]
        ids = [i for i in dict.fromkeys(ids) if i in kind_of]
        title = titles.get(key, key)
        text = f"{title}: {_sentence(_clip(str(latest['summary'])))}"
        if ids and all(kind_of[i] == "assisted" for i in ids):
            text += " That was with help, so it counts as practice, not as mastery."
        else:
            text += f" It moved from {latest['from_stage']} to {latest['to_stage']}."
        segments.append(
            Segment(
                id=f"growth-{key}",
                kind="growth",
                text=text,
                focus=f"plant:{key}",
                concept_key=key,
                evidence_ids=ids,
            )
        )
    return segments


def build_script(data: GardenData, as_of: datetime | None = None) -> RecapScript:
    now = as_of or data.now
    start, end = week_window(now)
    week_query = Query(date_from=start, date_to=end)
    dataset = build_dataset(data)
    changes = answer_metric(data, "recent_changes", week_query, dataset=dataset)
    independence = answer_metric(data, "independence_ratio", week_query, dataset=dataset)
    practice = answer_metric(data, "practice_time", week_query, dataset=dataset)
    due = answer_metric(data, "reviews_due", Query(), dataset=dataset)
    weakest = answer_metric(data, "weakest_concepts", Query(), dataset=dataset)

    growth = _growth_segments(data, dataset, changes)
    quiet = not growth
    segments: list[Segment] = [
        Segment(
            id="intro",
            kind="intro",
            text=(
                f"Here is your garden for {start:%B} {start.day} to {end:%B} {end.day}."
                if not quiet
                else (
                    f"Here is your garden for {start:%B} {start.day} to {end:%B} {end.day}. "
                    "Nothing new grew this week, and I will not pretend otherwise."
                )
            ),
        ),
        *growth,
    ]

    pd = practice.data
    ind = independence.data
    if pd["total_minutes"] or ind["independent"] or ind["assisted"]:
        parts = []
        if pd["total_minutes"]:
            parts.append(
                f"You practised {pd['hours']} hours across {pd['active_days']} days, "
                f"with a {pd['streak_days']}-day streak."
            )
        if ind["independent"] or ind["assisted"]:
            parts.append(
                f"{ind['independent']} piece{'s' if ind['independent'] != 1 else ''} of evidence "
                f"came from your own work and {ind['assisted']} had help."
            )
        segments.append(
            Segment(
                id="practice",
                kind="practice",
                text=" ".join(parts),
                evidence_ids=independence.citations,
            )
        )

    next_parts: list[str] = []
    next_keys: list[str] = []
    next_ids: list[str] = []
    if due.data["count"]:
        first = due.data["concepts"][0]
        next_parts.append(
            f"{due.data['count']} review{'s are' if due.data['count'] != 1 else ' is'} due, "
            f"starting with {first['title']}."
        )
        next_keys.append(str(first["concept_id"]))
        next_ids += due.citations
    if weakest.data["concepts"]:
        w = weakest.data["concepts"][0]
        if str(w["concept_id"]) not in next_keys:
            next_parts.append(f"Your weakest plant right now is {w['title']}.")
            next_keys.append(str(w["concept_id"]))
            next_ids += weakest.citations
    if next_parts:
        segments.append(
            Segment(
                id="next",
                kind="next",
                text=" ".join([*next_parts, "Ten focused minutes there is the best next step."]),
                focus=f"plant:{next_keys[0]}",
                concept_key=next_keys[0],
                evidence_ids=list(dict.fromkeys(next_ids)),
            )
        )
    segments.append(
        Segment(id="outro", kind="outro", text="That is your week. See you in the garden.")
    )

    allowed = {e.id for e in dataset.evidence}
    narration = ""
    for seg in segments:
        seg.evidence_ids = [i for i in dict.fromkeys(seg.evidence_ids) if i in allowed]
        seg.start_char = len(narration)
        narration += seg.text
        seg.end_char = len(narration)
        narration += " "
    return RecapScript(
        week=iso_week(end),
        week_start=start,
        week_end=end,
        segments=segments,
        narration=narration.strip(),
        rules_version=data.view.rule_ver or "none",
        quiet=quiet,
    )
