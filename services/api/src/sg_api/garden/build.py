"""Pure builders: `GardenData` to the snapshot and the dashboard dataset.

Product rules enforced here, not left to the UI:
- A growth event is emitted only when it cites evidence (`GrowthEventOut.evidence_ids` is
  non-empty). Revisions without citations, such as decay, never appear as growth.
- Assisted evidence stays `kind="assisted"`; it is never folded into the independent scores.
- Stored text (quotes, rationales, memories) is passed through as data, flattened to one line.
"""

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Literal

from sg_api.garden.data import (
    AssessmentRec,
    ConceptRec,
    EvidenceRec,
    GardenData,
    MemoryRec,
    RevisionRec,
)
from sg_api.garden.schemas import (
    DimensionScoreOut,
    EvidenceOut,
    FreshnessOut,
    GardenDatasetOut,
    GardenSnapshotOut,
    GroveOut,
    GroveSnapshotOut,
    GrowthEventOut,
    MemoryOut,
    MisconceptionOut,
    NextBestOut,
    PlantMetaOut,
    PlantSnapshotOut,
    PrerequisiteEdgeOut,
    ReadinessModelOut,
    RevisionOut,
    SessionMarkerOut,
)
from sg_core.memory.projections import GardenView, PlantView, change_after
from sg_core.memory.ranking import sanitize

DIMENSIONS = ("explanation", "application", "transfer", "retention")
DIMENSION_PART = {
    "explanation": "roots",
    "application": "stem",
    "transfer": "branches",
    "retention": "blossoms",
}
# Order the groves appear in; unknown domains follow alphabetically.
GROVE_TITLES = {
    "dsa": "Data structures & algorithms",
    "os": "Operating systems",
    "networks": "Computer networks",
    "databases": "Databases",
    "system_design": "System design",
    "behavioral": "Behavioral",
}
GROWTH_STAGES = ("unassessed", "sprouting", "assisted", "independent", "transfer", "retained")
READINESS_VERSION = "readiness@1"
READINESS_WEIGHTS = {"explanation": 0.3, "application": 0.35, "transfer": 0.2, "retention": 0.15}
MAX_QUOTE_CHARS = 600


def grove_title(domain: str) -> str:
    return GROVE_TITLES.get(domain, domain.replace("_", " ").capitalize())


def grove_order(domains: set[str]) -> list[str]:
    known = [d for d in GROVE_TITLES if d in domains]
    return known + sorted(domains - set(GROVE_TITLES))


def iso(moment: datetime) -> str:
    return moment.isoformat()


def stage_of_status(status: str, last_stage: str | None = None) -> str:
    """Plant statuses `due` and `wilting` overlay a growth stage; the stage is whatever the plant
    last reached (an assessed plant that is overdue was at least independent)."""
    if status in GROWTH_STAGES:
        return status
    return last_stage or "independent"


# ── Snapshot ──
def _scores(plant: PlantView) -> dict[str, DimensionScoreOut]:
    out: dict[str, DimensionScoreOut] = {}
    for dim in DIMENSIONS:
        raw = plant.dimension_scores.get(dim)
        raw = raw if isinstance(raw, dict) else {}
        out[dim] = DimensionScoreOut(
            independent=_unit(raw.get("independent")), assisted=_unit(raw.get("assisted"))
        )
    return out


def _unit(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def build_snapshot(data: GardenData, view: GardenView | None = None) -> GardenSnapshotOut:
    """The `GardenSnapshot` for `view` (default: the garden now). `conceptId` is the stable
    concept key, so snapshots from different curriculum versions line up."""
    view = view or data.view
    revision = next((r for r in data.revisions if r.rev == view.rev), None)
    created_at = revision.created_at if revision else data.now
    cutoff = created_at if revision else None

    counts: dict[uuid.UUID, int] = defaultdict(int)
    for e in data.evidence:
        if cutoff is None or e.occurred_at <= cutoff:
            counts[e.concept_id] += 1

    domains = {p.domain for p in view.plants}
    plants = [
        PlantSnapshotOut(
            concept_id=p.key,
            grove_id=p.domain,
            label=p.title,
            status=p.status,
            dimensions=_scores(p),
            evidence_count=counts.get(p.concept_id, 0),
            last_evidence_at=iso(p.last_evidence_at) if p.last_evidence_at else None,
            next_review_at=iso(p.next_review_at) if p.next_review_at else None,
        )
        for p in sorted(view.plants, key=lambda p: p.key)
    ]
    keys = {p.concept_id: p.key for p in view.plants}
    edges = sorted({(keys[a], keys[b]) for a, b in data.edges if a in keys and b in keys})
    return GardenSnapshotOut(
        revision=view.rev,
        rule_version=view.rule_ver or "none",
        created_at=iso(created_at),
        groves=[GroveSnapshotOut(id=d, label=grove_title(d)) for d in grove_order(domains)],
        plants=plants,
        prerequisites=[PrerequisiteEdgeOut(from_=a, to=b) for a, b in edges],
    )


def build_revisions(data: GardenData) -> list[RevisionOut]:
    return [
        RevisionOut(
            rev=r.rev, rule_version=r.rule_ver, reason=r.reason, created_at=iso(r.created_at)
        )
        for r in data.revisions
    ]


# ── Evidence ──
def assessments_by_evidence(data: GardenData) -> dict[uuid.UUID, list[AssessmentRec]]:
    out: dict[uuid.UUID, list[AssessmentRec]] = defaultdict(list)
    for a in sorted(data.assessments, key=lambda a: a.created_at):
        for eid in a.evidence_ids:
            out[eid].append(a)
    return out


def _weight(a: AssessmentRec) -> float:
    if a.outcome in ("not_demonstrated", "unassessable"):
        return 0.0
    if a.score is not None:
        return _unit(a.score)
    return 0.8 if a.outcome == "demonstrated" else 0.4


def _source(e: EvidenceRec) -> Literal["transcript", "code", "tests"]:
    if e.has_run:
        return "tests"
    if e.has_code or e.kind == "code_run":
        return "code"
    return "transcript"


def build_evidence(
    data: GardenData, concept_keys: dict[uuid.UUID, str] | None = None
) -> list[EvidenceOut]:
    keys = concept_keys or {c.id: c.key for c in data.concepts.values()}
    judged = assessments_by_evidence(data)
    sessions = {s.id: s for s in data.sessions}
    out: list[EvidenceOut] = []
    for e in sorted(data.evidence, key=lambda e: e.occurred_at):
        key = keys.get(e.concept_id)
        if key is None:
            continue
        assessments = judged.get(e.id, [])
        live = [a for a in assessments if a.status != "rejected"]
        if assessments and not live:
            continue  # the judge pipeline rejected every verdict on it: not usable evidence
        latest = live[-1] if live else None
        confirmed = any(a.status == "accepted" for a in live)
        independent = e.assistance == "independent"
        sess = sessions.get(e.session_id)
        out.append(
            EvidenceOut(
                id=str(e.id),
                plant_key=key,
                dimension=e.dimension,
                kind="independent" if independent else "assisted",
                character=sess.character if sess else "drona",
                session_id=str(e.session_id),
                occurred_at=iso(e.occurred_at),
                quote=sanitize(e.quote or "", MAX_QUOTE_CHARS),
                source=_source(e),
                rationale=sanitize(latest.rationale, 600) if latest else "Awaiting the judge.",
                assist_note=(
                    None
                    if independent
                    else (f"{e.hint_count} hint(s) used" if e.hint_count else "Assisted")
                ),
                confidence=round(
                    1 - _unit(latest.uncertainty if latest.uncertainty is not None else 0.3), 3
                )
                if latest
                else 0.5,
                weight=round(_weight(latest), 3) if latest else 0.5,
                rubric_version=f"rubric@{latest.rubric_ver}"
                if latest and latest.rubric_ver
                else "rubric@1",
                status="confirmed" if confirmed else "provisional",
            )
        )
    return out


# ── Growth events ──
def _event_dimension(change: dict[str, Any]) -> str | None:
    for event in change.get("events") or []:
        if isinstance(event, dict) and event.get("dimension") in DIMENSIONS:
            return str(event["dimension"])
    return None


def _change_evidence(change: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for event in change.get("events") or []:
        if isinstance(event, dict):
            ids.extend(str(i) for i in event.get("evidence_ids") or [])
    return list(dict.fromkeys(ids))


def _status_pair(change: dict[str, Any]) -> tuple[str | None, str | None]:
    status = change.get("status")
    if isinstance(status, dict):
        return status.get("before"), status.get("after")
    before, after = change.get("before"), change.get("after")
    return (
        before.get("status") if isinstance(before, dict) else None,
        after.get("status") if isinstance(after, dict) else None,
    )


def build_growth_events(
    data: GardenData, visible_evidence: set[str] | None = None
) -> list[GrowthEventOut]:
    """One event per concept change that cites evidence, oldest revision first. `visible_evidence`
    restricts citations to evidence that is shown (rejected evidence is not)."""
    by_key = {c.key: c.id for c in data.concepts.values()}
    keys = {c.id: c.key for c in data.concepts.values()}
    assessments = {a.id: a for a in data.assessments}
    last_stage: dict[str, str] = {}
    events: list[GrowthEventOut] = []

    for revision in sorted(data.revisions, key=lambda r: r.rev):
        for change in revision.changes:
            resolved = change_after(change, by_key)
            if resolved is None:
                continue
            concept_id, _ = resolved
            key = keys.get(concept_id)
            if key is None:
                continue
            before_status, after_status = _status_pair(change)
            before = stage_of_status(before_status or "unassessed", last_stage.get(key))
            after = stage_of_status(after_status or before, last_stage.get(key))
            last_stage[key] = after if after != "unassessed" else last_stage.get(key, after)

            evidence_ids = _change_evidence(change)
            dimension = _event_dimension(change)
            if not evidence_ids:  # shape without per-event citations: use the revision's verdicts
                for aid in revision.assessment_ids:
                    a = assessments.get(aid)
                    if a and a.concept_id == concept_id and a.status != "rejected":
                        evidence_ids.extend(str(i) for i in a.evidence_ids)
                        dimension = dimension or (
                            a.dimension if a.dimension in DIMENSIONS else None
                        )
                evidence_ids = list(dict.fromkeys(evidence_ids))
            if visible_evidence is not None:
                evidence_ids = [i for i in evidence_ids if i in visible_evidence]
            if not evidence_ids or dimension is None:
                continue  # growth without a citation is not shown
            part = DIMENSION_PART[dimension]
            summary = f"{part.capitalize()} grew"
            if after != before:
                summary += f"; now {after}"
            events.append(
                GrowthEventOut(
                    id=f"rev{revision.rev}:{key}",
                    plant_key=key,
                    occurred_at=iso(revision.created_at),
                    dimension=dimension,
                    from_stage=before,
                    to_stage=after,
                    summary=summary,
                    evidence_ids=evidence_ids,
                    revision=revision.rev,
                )
            )
    return events


# ── Sessions, memories, misconceptions, next best ──
def build_sessions(data: GardenData, evidence: list[EvidenceOut]) -> list[SessionMarkerOut]:
    by_session: dict[str, list[str]] = defaultdict(list)
    for e in evidence:
        by_session[e.session_id].append(e.id)
    out = []
    for s in sorted(data.sessions, key=lambda s: s.started_at):
        mode = s.mode.replace("_", " ")
        out.append(
            SessionMarkerOut(
                id=str(s.id),
                character=s.character,
                started_at=iso(s.started_at),
                minutes=max(0, round((s.duration_seconds or 0) / 60)),
                title=f"{s.character.capitalize()}: {mode}",
                evidence_ids=by_session.get(str(s.id), []),
            )
        )
    return out


_SOURCE_WHY = {
    "user": "You told us this, or corrected it.",
    "agent": "A mentor noticed this during a session.",
    "evidence_pipeline": "Confirmed from your evidence.",
    "system": "Recorded by the system.",
}


def build_memory(m: MemoryRec) -> MemoryOut:
    why = m.data.get("why")
    status = m.status if m.status in ("provisional", "accepted", "disputed") else "provisional"
    return MemoryOut(
        id=str(m.id),
        character=m.source_character or ("sanjaya" if m.source == "system" else "drona"),
        layer=m.layer,
        text=sanitize(m.content, 2000),
        why=sanitize(str(why), 300) if isinstance(why, str) else _SOURCE_WHY.get(m.source, ""),
        status=status,
        confidence=_unit(m.confidence if m.confidence is not None else 0.5),
        evidence_ids=[str(i) for i in m.evidence_ids],
        affects=m.affects,
        deletable=m.layer == "private",
        created_at=iso(m.created_at),
    )


def build_misconceptions(data: GardenData) -> list[MisconceptionOut]:
    """Misconception memories, one per concept statement. Only those backed by evidence appear."""
    out = []
    for m in data.memories:
        if m.kind != "misconception" or not m.evidence_ids:
            continue
        key = m.data.get("concept_key")
        if not isinstance(key, str):
            continue
        occurrences = m.data.get("occurrences")
        out.append(
            MisconceptionOut(
                id=str(m.id),
                plant_key=key,
                text=sanitize(m.content, 300),
                occurrences=occurrences if isinstance(occurrences, int) and occurrences > 0 else 1,
                last_seen_at=iso(m.created_at),
                evidence_ids=[str(i) for i in m.evidence_ids],
            )
        )
    return sorted(out, key=lambda x: x.last_seen_at, reverse=True)


def _last_evidence_ids(evidence: list[EvidenceOut], key: str, limit: int = 2) -> list[str]:
    return [e.id for e in evidence if e.plant_key == key][-limit:]


def build_next_best(data: GardenData, evidence: list[EvidenceOut]) -> list[NextBestOut]:
    """Up to three suggestions, each citing evidence: overdue reviews first, then plants whose
    only evidence is assisted. Deterministic, so the same garden gives the same advice."""
    picks: list[NextBestOut] = []
    plants = sorted(data.view.plants, key=lambda p: (p.next_review_at or data.now, p.key))
    for p in plants:
        if p.status in ("due", "wilting"):
            cited = _last_evidence_ids(evidence, p.key)
            if cited:
                picks.append(
                    NextBestOut(
                        character="drona" if p.domain != "behavioral" else "vidura",
                        plant_key=p.key,
                        title=f"Quick recall check on {p.title}",
                        reason="Its review is overdue, so the plant is wilting."
                        if p.status == "wilting"
                        else "A review is due to keep this plant growing.",
                        minutes=8,
                        evidence_ids=cited,
                    )
                )
    for p in sorted(data.view.plants, key=lambda p: p.key):
        if p.status == "assisted":
            cited = _last_evidence_ids(evidence, p.key)
            if cited:
                picks.append(
                    NextBestOut(
                        character={"behavioral": "vidura", "dsa": "arjuna"}.get(p.domain, "drona"),
                        plant_key=p.key,
                        title=f"Show {p.title} without hints",
                        reason="Everything so far was assisted: no independent evidence yet.",
                        minutes=20,
                        evidence_ids=cited,
                    )
                )
    return picks[:3]


# ── Dataset ──
def build_dataset(data: GardenData) -> GardenDatasetOut:
    keys = {c.id: c.key for c in data.concepts.values()}
    evidence = build_evidence(data, keys)
    shown = {e.id for e in evidence}
    concepts: list[ConceptRec] = sorted(data.concepts.values(), key=lambda c: (c.domain, c.key))
    domains = {c.domain for c in concepts}
    latest = data.revisions[-1] if data.revisions else None
    snapshot = build_snapshot(data)
    return GardenDatasetOut(
        generated_at=iso(data.now),
        freshness=FreshnessOut(
            projection_at=iso(latest.created_at if latest else data.now),
            rules_version=data.view.rule_ver or "none",
            curriculum=data.curriculum,
        ),
        readiness=ReadinessModelOut(
            version=READINESS_VERSION,
            target_role=data.target_role,
            dimension_weights=dict(READINESS_WEIGHTS),
        ),
        groves=[GroveOut(id=d, title=grove_title(d)) for d in grove_order(domains)],
        plants=[
            PlantMetaOut(
                key=c.key, title=c.title, grove=c.domain, difficulty=min(5, max(1, c.difficulty))
            )
            for c in concepts
        ],
        evidence=evidence,
        growth_events=build_growth_events(data, shown),
        sessions=build_sessions(data, evidence),
        memories=[build_memory(m) for m in data.memories],
        misconceptions=build_misconceptions(data),
        next_best=build_next_best(data, evidence),
        streak_days=data.streak_days,
        prerequisites=snapshot.prerequisites,
    )


def revision_at(data: GardenData, rev: int) -> RevisionRec | None:
    return next((r for r in data.revisions if r.rev == rev), None)
