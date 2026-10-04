"""Read-side projections over memory and evidence: the garden view and analytics summary.

These only read. Garden rows are written by the rules engine (C10/C11); this module presents
them, with citations, for the dashboard (C14) and for agents. Assisted and independent figures
are always reported separately.

Time travel replays append-only `garden_revisions`. Each entry of `GardenRevision.changes` is
expected to look like `{"concept_id": "<uuid>", "before": {...}, "after": {"status": "...",
"dimension_scores": {...}}}` (C10 owns the writer and should keep this shape).
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.models.curriculum import Concept, Curriculum
from sg_core.models.enums import (
    AssessmentStatus,
    Assistance,
    CurriculumStatus,
    PlantStatus,
)
from sg_core.models.evidence import Assessment, EvidenceItem, GardenRevision, PlantState

# Revision reasons that must cite assessments (and through them, evidence).
EVIDENCE_REASONS = frozenset({"assessment", "correction"})


@dataclass
class PlantView:
    concept_id: uuid.UUID
    key: str
    title: str
    domain: str
    status: str
    dimension_scores: dict[str, Any]
    last_evidence_at: datetime | None = None
    next_review_at: datetime | None = None


@dataclass
class GardenView:
    rev: int
    rule_ver: str | None
    plants: list[PlantView]


async def _concepts(session: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, Concept]:
    """Concepts of the active curricula plus any the learner has a plant for."""
    active = (
        select(Concept)
        .join(Curriculum, Curriculum.id == Concept.curriculum_id)
        .where(Curriculum.status == CurriculumStatus.ACTIVE)
    )
    planted = (
        select(Concept)
        .join(PlantState, PlantState.concept_id == Concept.id)
        .where(PlantState.user_id == user_id)
    )
    found: dict[uuid.UUID, Concept] = {}
    for query in (active, planted):
        for concept in (await session.scalars(query)).all():
            found[concept.id] = concept
    return found


async def garden_view(
    session: AsyncSession, user_id: uuid.UUID, *, rev: int | None = None
) -> GardenView:
    """The garden now, or as it was at revision `rev` (time travel)."""
    concepts = await _concepts(session, user_id)
    latest = await session.scalar(
        select(GardenRevision)
        .where(GardenRevision.user_id == user_id)
        .order_by(GardenRevision.rev.desc())
        .limit(1)
    )
    states: dict[uuid.UUID, dict[str, Any]] = {}
    rule_ver: str | None = latest.rule_ver if latest else None
    current_rev = latest.rev if latest else 0

    if rev is None:
        plants = (
            await session.scalars(select(PlantState).where(PlantState.user_id == user_id))
        ).all()
        for plant in plants:
            states[plant.concept_id] = {
                "status": plant.status.value,
                "dimension_scores": plant.dimension_scores,
                "last_evidence_at": plant.last_evidence_at,
                "next_review_at": plant.next_review_at,
            }
    else:
        revisions = (
            await session.scalars(
                select(GardenRevision)
                .where(GardenRevision.user_id == user_id, GardenRevision.rev <= rev)
                .order_by(GardenRevision.rev)
            )
        ).all()
        for revision in revisions:
            for change in revision.changes:
                after = change.get("after")
                try:
                    concept_id = uuid.UUID(str(change["concept_id"]))
                except (KeyError, ValueError):
                    continue
                if isinstance(after, dict):
                    states[concept_id] = {**states.get(concept_id, {}), **after}
        current_rev = revisions[-1].rev if revisions else 0
        rule_ver = revisions[-1].rule_ver if revisions else None

    views = []
    for concept_id, concept in concepts.items():
        state = states.get(concept_id, {})
        views.append(
            PlantView(
                concept_id=concept_id,
                key=concept.key,
                title=concept.title,
                domain=concept.domain,
                status=str(state.get("status", PlantStatus.UNASSESSED.value)),
                dimension_scores=state.get("dimension_scores") or {},
                last_evidence_at=state.get("last_evidence_at"),
                next_review_at=state.get("next_review_at"),
            )
        )
    views.sort(key=lambda v: (v.domain, v.key))
    return GardenView(rev=current_rev, rule_ver=rule_ver, plants=views)


@dataclass
class CitedAssessment:
    id: uuid.UUID
    concept_id: uuid.UUID
    dimension: str
    outcome: str
    assistance: str
    rationale: str
    evidence_ids: list[uuid.UUID]


@dataclass
class GrowthEvent:
    rev: int
    reason: str
    rule_ver: str
    created_at: datetime
    assessments: list[CitedAssessment] = field(default_factory=list)

    @property
    def evidence_ids(self) -> list[uuid.UUID]:
        return list(dict.fromkeys(e for a in self.assessments for e in a.evidence_ids))

    @property
    def cited(self) -> bool:
        return bool(self.evidence_ids)

    @property
    def assistance_breakdown(self) -> dict[str, int]:
        counts = {a.value: 0 for a in Assistance}
        for assessment in self.assessments:
            counts[assessment.assistance] = counts.get(assessment.assistance, 0) + 1
        return counts


async def growth_events(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int = 50
) -> list[GrowthEvent]:
    """Garden revisions, newest first, each with the assessments and evidence that caused it.
    This is what the 'what changed and why' feed and the memory panel show."""
    revisions = (
        await session.scalars(
            select(GardenRevision)
            .where(GardenRevision.user_id == user_id)
            .order_by(GardenRevision.rev.desc())
            .limit(limit)
        )
    ).all()
    wanted = {a for r in revisions for a in r.assessment_ids}
    by_id: dict[uuid.UUID, Assessment] = {}
    if wanted:
        by_id = {
            a.id: a
            for a in (
                await session.scalars(
                    select(Assessment).where(
                        Assessment.user_id == user_id, Assessment.id.in_(wanted)
                    )
                )
            ).all()
        }
    events = []
    for revision in revisions:
        cited = [
            CitedAssessment(
                id=a.id,
                concept_id=a.concept_id,
                dimension=a.dimension.value,
                outcome=a.outcome.value,
                assistance=a.assistance.value,
                rationale=a.rationale,
                evidence_ids=list(a.evidence_ids),
            )
            for a in (by_id.get(i) for i in revision.assessment_ids)
            if a is not None and a.status is not AssessmentStatus.REJECTED
        ]
        events.append(
            GrowthEvent(
                rev=revision.rev,
                reason=revision.reason,
                rule_ver=revision.rule_ver,
                created_at=revision.created_at,
                assessments=cited,
            )
        )
    return events


async def uncited_growth(session: AsyncSession, user_id: uuid.UUID) -> list[int]:
    """Revision numbers that grew the garden without citing evidence. Should always be empty;
    used by tests and the C23 audit."""
    events = await growth_events(session, user_id, limit=10_000)
    return [e.rev for e in events if e.reason in EVIDENCE_REASONS and not e.cited]


@dataclass
class AnalyticsSummary:
    concepts_by_status: dict[str, int]
    evidence_independent: int
    evidence_assisted: int
    independent_problem_families: int
    reviews_due: int
    reviews_overdue: int
    streak_days: int
    # {"2026-09-28": {"independent": 3, "assisted": 1}} keyed by ISO week start, per dimension.
    weekly: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)

    @property
    def independent_to_assisted(self) -> float | None:
        if self.evidence_assisted == 0:
            return None
        return self.evidence_independent / self.evidence_assisted


def streak_from_days(days: set[date], today: date) -> int:
    """Consecutive active days ending today, or yesterday (today may not be over yet)."""
    cursor = today if today in days else today - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


async def analytics_summary(
    session: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None, weeks: int = 12
) -> AnalyticsSummary:
    moment = now or datetime.now(UTC)
    concepts = await _concepts(session, user_id)
    status_counts = {s.value: 0 for s in PlantStatus}
    plants = (await session.scalars(select(PlantState).where(PlantState.user_id == user_id))).all()
    planted = {p.concept_id for p in plants}
    for plant in plants:
        status_counts[plant.status.value] += 1
    status_counts[PlantStatus.UNASSESSED.value] += len(set(concepts) - planted)

    overdue = sum(1 for p in plants if p.next_review_at is not None and p.next_review_at < moment)
    due = sum(
        1
        for p in plants
        if p.status in (PlantStatus.DUE, PlantStatus.WILTING)
        or (p.next_review_at is not None and p.next_review_at <= moment)
    )

    counts = dict(
        (
            await session.execute(
                select(EvidenceItem.assistance, func.count())
                .where(EvidenceItem.user_id == user_id)
                .group_by(EvidenceItem.assistance)
            )
        ).all()
    )
    families = await session.scalar(
        select(func.count(func.distinct(EvidenceItem.problem_family))).where(
            EvidenceItem.user_id == user_id,
            EvidenceItem.assistance == Assistance.INDEPENDENT.value,
            EvidenceItem.problem_family.is_not(None),
        )
    )

    week = func.date_trunc("week", EvidenceItem.occurred_at)
    series = await session.execute(
        select(week, EvidenceItem.dimension, EvidenceItem.assistance, func.count())
        .where(
            EvidenceItem.user_id == user_id,
            EvidenceItem.occurred_at >= moment - timedelta(weeks=weeks),
        )
        .group_by(week, EvidenceItem.dimension, EvidenceItem.assistance)
        .order_by(week)
    )
    weekly: dict[str, dict[str, dict[str, int]]] = {}
    for start, dimension, assistance, count in series:
        bucket = weekly.setdefault(f"{start:%Y-%m-%d}", {}).setdefault(dimension.value, {})
        bucket[assistance.value] = int(count)

    day = func.date(func.timezone("UTC", EvidenceItem.occurred_at))
    days = {
        d
        for (d,) in (
            await session.execute(select(day).where(EvidenceItem.user_id == user_id).distinct())
        )
    }

    return AnalyticsSummary(
        concepts_by_status=status_counts,
        evidence_independent=int(counts.get(Assistance.INDEPENDENT, 0)),
        evidence_assisted=int(counts.get(Assistance.ASSISTED, 0)),
        independent_problem_families=int(families or 0),
        reviews_due=due,
        reviews_overdue=overdue,
        streak_days=streak_from_days(days, moment.date()),
        weekly=weekly,
    )
