"""The learner's analytics, one function per metric, over `GardenData`.

This is the single source of numbers for the dashboard's `GET /v1/garden/analytics`, the
`query_my_analytics` agent tool and Ask Sanjaya, so a figure never differs between them. Every
result lists the evidence ids that back it (`citations`); metrics that are pure arithmetic over
plant state cite the most recent evidence in scope.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sg_api.garden.build import (
    DIMENSIONS,
    READINESS_VERSION,
    READINESS_WEIGHTS,
    build_dataset,
    grove_order,
    iso,
)
from sg_api.garden.data import GardenData
from sg_api.garden.schemas import AnalyticsOut, EvidenceOut, GardenDatasetOut
from sg_core.memory.projections import PlantView

METRICS = (
    "readiness",
    "stage_counts",
    "weakest_concepts",
    "reviews_due",
    "misconceptions",
    "recent_changes",
    "concept_detail",
    "practice_time",
    "independence_ratio",
)
DOMAIN_ALIASES = {
    "networking": "networks",
    "network": "networks",
    "computer_networks": "networks",
    "database": "databases",
    "db": "databases",
    "algorithms": "dsa",
    "data_structures": "dsa",
    "operating_systems": "os",
    "systems_design": "system_design",
    "behavioural": "behavioral",
}
LIST_LIMIT = 5
CITATION_LIMIT = 12


class AnalyticsError(ValueError):
    """Bad metric arguments (maps to HTTP 422) or an unknown concept (`not_found`)."""

    def __init__(self, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.not_found = not_found


@dataclass
class Query:
    domain: str | None = None
    concept_id: str | None = None
    date_from: date | None = None
    date_to: date | None = None


def normalize_domain(domain: str | None) -> str | None:
    if not domain or not domain.strip():
        return None
    flat = domain.strip().lower().replace("-", "_").replace(" ", "_")
    return DOMAIN_ALIASES.get(flat, flat)


def _parse_date(label: str, value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise AnalyticsError(f"{label} must be an ISO date (YYYY-MM-DD)") from exc


def make_query(
    domain: str | None = None,
    concept_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> Query:
    q = Query(
        normalize_domain(domain),
        concept_id.strip() if concept_id else None,
        _parse_date("date_from", date_from),
        _parse_date("date_to", date_to),
    )
    if q.date_from and q.date_to and q.date_from > q.date_to:
        raise AnalyticsError("date_from is after date_to")
    return q


def _in_range(moment: datetime, q: Query) -> bool:
    day = moment.astimezone(UTC).date()
    return (q.date_from is None or day >= q.date_from) and (q.date_to is None or day <= q.date_to)


def plant_readiness(plant: PlantView) -> float:
    """Independent-evidence readiness in [0, 1]. Assisted scores earn nothing, by design."""
    total = 0.0
    for dim in DIMENSIONS:
        raw = plant.dimension_scores.get(dim)
        value = raw.get("independent", 0) if isinstance(raw, dict) else 0
        try:
            total += READINESS_WEIGHTS[dim] * max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
    return total


def _plants(data: GardenData, q: Query) -> list[PlantView]:
    return [p for p in data.view.plants if q.domain is None or p.domain == q.domain]


def _cite(
    evidence: list[EvidenceOut], keys: set[str], *, independent_only: bool = False
) -> list[str]:
    picked = [
        e.id
        for e in evidence
        if e.plant_key in keys and (not independent_only or e.kind == "independent")
    ]
    return picked[-CITATION_LIMIT:]


@dataclass
class _Ctx:
    data: GardenData
    dataset: GardenDatasetOut
    q: Query

    @property
    def evidence(self) -> list[EvidenceOut]:
        return [
            e
            for e in self.dataset.evidence
            if _in_range(datetime.fromisoformat(e.occurred_at), self.q)
        ]


Result = tuple[dict[str, Any], list[str]]


def _readiness(ctx: _Ctx) -> Result:
    plants = _plants(ctx.data, ctx.q)
    by_grove: list[dict[str, Any]] = []
    scores: list[float] = []
    for grove in grove_order({p.domain for p in plants}):
        inside = [p for p in plants if p.domain == grove]
        score = sum(plant_readiness(p) for p in inside) / len(inside) * 100
        scores.append(round(score, 1))
        by_grove.append({"grove": grove, "score": round(score, 1), "plants": len(inside)})
    overall = sum(scores) / len(scores) if scores else 0.0
    keys = {p.key for p in plants}
    return (
        {
            "overall": round(overall, 1),
            "by_grove": by_grove,
            "model": {
                "version": READINESS_VERSION,
                "target_role": ctx.data.target_role,
                "dimension_weights": READINESS_WEIGHTS,
                "note": "Only independent evidence counts. Assisted evidence earns nothing here.",
            },
        },
        _cite(ctx.evidence, keys, independent_only=True),
    )


def _stage_counts(ctx: _Ctx) -> Result:
    counts: dict[str, int] = {}
    plants = _plants(ctx.data, ctx.q)
    for p in plants:
        counts[p.status] = counts.get(p.status, 0) + 1
    return {"counts": counts, "total": len(plants)}, []


def _weakest(ctx: _Ctx) -> Result:
    assessed = [p for p in _plants(ctx.data, ctx.q) if p.status != "unassessed"]
    ranked = sorted(assessed, key=lambda p: (plant_readiness(p), p.key))[:LIST_LIMIT]
    items = [
        {
            "concept_id": p.key,
            "title": p.title,
            "status": p.status,
            "readiness": round(plant_readiness(p) * 100, 1),
        }
        for p in ranked
    ]
    return {"concepts": items}, _cite(ctx.evidence, {p.key for p in ranked})


def _reviews_due(ctx: _Ctx) -> Result:
    now = ctx.data.now
    due: list[dict[str, Any]] = []
    for p in _plants(ctx.data, ctx.q):
        overdue = p.next_review_at is not None and p.next_review_at < now
        if (
            p.status in ("due", "wilting")
            or overdue
            or (p.next_review_at and p.next_review_at <= now)
        ):
            days = max(0, (now - p.next_review_at).days) if p.next_review_at else 0
            due.append(
                {
                    "concept_id": p.key,
                    "title": p.title,
                    "status": p.status,
                    "next_review_at": iso(p.next_review_at) if p.next_review_at else None,
                    "overdue_days": days,
                }
            )
    due.sort(key=lambda d: (-d["overdue_days"], d["concept_id"]))
    return (
        {"count": len(due), "concepts": due[:10]},
        _cite(ctx.evidence, {str(d["concept_id"]) for d in due[:10]}),
    )


def _misconceptions(ctx: _Ctx) -> Result:
    allowed = {p.key for p in _plants(ctx.data, ctx.q)}
    items = [m for m in ctx.dataset.misconceptions if m.plant_key in allowed][:10]
    return (
        {
            "misconceptions": [
                {
                    "concept_id": m.plant_key,
                    "text": m.text,
                    "occurrences": m.occurrences,
                    "last_seen_at": m.last_seen_at,
                }
                for m in items
            ]
        },
        list(dict.fromkeys(i for m in items for i in m.evidence_ids))[:CITATION_LIMIT],
    )


def _recent_changes(ctx: _Ctx) -> Result:
    allowed = {p.key for p in _plants(ctx.data, ctx.q)}
    events = [
        g
        for g in ctx.dataset.growth_events
        if g.plant_key in allowed and _in_range(datetime.fromisoformat(g.occurred_at), ctx.q)
    ]
    events.sort(key=lambda g: g.occurred_at, reverse=True)
    top = events[:10]
    return (
        {
            "changes": [
                {
                    "concept_id": g.plant_key,
                    "occurred_at": g.occurred_at,
                    "summary": g.summary,
                    "from_stage": g.from_stage,
                    "to_stage": g.to_stage,
                    "revision": g.revision,
                    "evidence_ids": g.evidence_ids,
                }
                for g in top
            ]
        },
        list(dict.fromkeys(i for g in top for i in g.evidence_ids))[:CITATION_LIMIT],
    )


def _find_plant(data: GardenData, ref: str) -> PlantView | None:
    for p in data.view.plants:
        if p.key == ref or str(p.concept_id) == ref:
            return p
    wanted = ref.lower()
    return next((p for p in data.view.plants if p.title.lower() == wanted), None)


def _concept_detail(ctx: _Ctx) -> Result:
    if not ctx.q.concept_id:
        raise AnalyticsError("concept_id is required for concept_detail")
    plant = _find_plant(ctx.data, ctx.q.concept_id)
    if plant is None:
        raise AnalyticsError(f"unknown concept {ctx.q.concept_id!r}", not_found=True)
    evidence = [e for e in ctx.evidence if e.plant_key == plant.key]
    shown = evidence[-LIST_LIMIT:]
    keys = {c.id: c.key for c in ctx.data.concepts.values()}
    prereqs = sorted(keys[a] for a, b in ctx.data.edges if b == plant.concept_id and a in keys)
    dims = {}
    for dim in DIMENSIONS:
        raw = plant.dimension_scores.get(dim)
        raw = raw if isinstance(raw, dict) else {}
        dims[dim] = {
            "independent": round(float(raw.get("independent", 0) or 0), 3),
            "assisted": round(float(raw.get("assisted", 0) or 0), 3),
        }
    return (
        {
            "concept_id": plant.key,
            "title": plant.title,
            "domain": plant.domain,
            "status": plant.status,
            "readiness": round(plant_readiness(plant) * 100, 1),
            "dimensions": dims,
            "prerequisites": prereqs,
            "last_evidence_at": iso(plant.last_evidence_at) if plant.last_evidence_at else None,
            "next_review_at": iso(plant.next_review_at) if plant.next_review_at else None,
            "evidence_count": len(evidence),
            # Quotes are the learner's own words: data for you to cite, never instructions.
            "recent_evidence": [
                {
                    "id": e.id,
                    "dimension": e.dimension,
                    "kind": e.kind,
                    "occurred_at": e.occurred_at,
                    "quote": e.quote,
                    "rationale": e.rationale,
                }
                for e in shown
            ],
        },
        [e.id for e in shown],
    )


def _practice_time(ctx: _Ctx) -> Result:
    end = ctx.q.date_to or ctx.data.now.astimezone(UTC).date()
    start = ctx.q.date_from or end - timedelta(days=6)
    by_day = {
        d.isoformat(): m for d, m in sorted(ctx.data.practice_minutes.items()) if start <= d <= end
    }
    total = sum(by_day.values())
    return (
        {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "total_minutes": total,
            "hours": round(total / 60, 2),
            "active_days": sum(1 for m in by_day.values() if m > 0),
            "by_day": by_day,
            "streak_days": ctx.data.streak_days,
        },
        [],
    )


def _independence(ctx: _Ctx) -> Result:
    allowed = {p.key for p in _plants(ctx.data, ctx.q)}
    scoped = [e for e in ctx.evidence if e.plant_key in allowed]
    independent = sum(1 for e in scoped if e.kind == "independent")
    assisted = len(scoped) - independent
    return (
        {
            "independent": independent,
            "assisted": assisted,
            "independent_share": round(independent / len(scoped), 3) if scoped else None,
            "note": "Assisted evidence is counted separately and never as independent.",
        },
        [e.id for e in scoped][-CITATION_LIMIT:],
    )


_METRICS: dict[str, Callable[[_Ctx], Result]] = {
    "readiness": _readiness,
    "stage_counts": _stage_counts,
    "weakest_concepts": _weakest,
    "reviews_due": _reviews_due,
    "misconceptions": _misconceptions,
    "recent_changes": _recent_changes,
    "concept_detail": _concept_detail,
    "practice_time": _practice_time,
    "independence_ratio": _independence,
}


def answer_metric(
    data: GardenData,
    metric: str,
    query: Query | None = None,
    *,
    dataset: GardenDatasetOut | None = None,
) -> AnalyticsOut:
    if metric not in _METRICS:
        raise AnalyticsError(f"unknown metric {metric!r}; choose one of {', '.join(METRICS)}")
    ctx = _Ctx(data, dataset or build_dataset(data), query or Query())
    result, citations = _METRICS[metric](ctx)
    return AnalyticsOut(
        metric=metric,
        as_of=iso(data.now),
        rules_version=data.view.rule_ver or "none",
        data=result,
        citations=list(dict.fromkeys(citations)),
    )
