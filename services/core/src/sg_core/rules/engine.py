"""The deterministic, versioned garden rules engine. Pure: no I/O, no clock, no randomness.

    propose(state, observations, now, profile) -> RulesResult

Persistent garden changes come only from here. Guarantees (each covered by tests):

* Deterministic: same state + observations + profile + `now` gives an identical result, and the
  order the observations are passed in does not matter (they are applied by time, then id).
* Idempotent: an assessment already in `state.applied`, or repeated in the batch, is a no-op.
* Cited: every growth event carries the assessment and evidence ids behind it; no evidence,
  no growth.
* Assisted evidence has its own track. It can only ever earn the ASSISTED ("ghost") stage and
  never feeds independent scores, the review schedule or retention.
* Monotonic: dimension scores never decrease. Time only overlays DUE then WILTING on a plant
  whose review is overdue; a successful review clears it, scores are untouched.
* Distinct problem families: repeats of the same family do not count again, and transfer needs a
  family different from the one credited for application.
* Ambiguous evidence (judge uncertainty above the profile limit, or NaN) grows nothing and is
  returned in `reassess` so the pipeline can re-judge it.
* Out-of-order evidence is never applied incrementally. An observation older than its plant's
  `last_evidence_at` is skipped as `out_of_order` and not consumed (it stays out of `applied` and
  `processed`), because applying it on top of newer evidence could differ from `replay()`. The
  caller (C11) must then rebuild the garden with `replay()` over all of its observations.
"""

import math
import uuid
from collections.abc import Collection, Iterable
from dataclasses import replace
from datetime import datetime, timedelta

from sg_core.models.enums import AssessmentOutcome, Assistance, Dimension, PlantStatus
from sg_core.rules.profile import RulesProfile
from sg_core.rules.types import (
    ENGINE_VERSION,
    GROWTH_DIMENSIONS,
    DimensionState,
    GardenState,
    GrowthEvent,
    Observation,
    PlantChange,
    PlantState,
    RulesResult,
    Skipped,
    SkipReason,
)

_EXPLANATION = Dimension.EXPLANATION.value
_APPLICATION = Dimension.APPLICATION.value
_TRANSFER = Dimension.TRANSFER.value
_RETENTION = Dimension.RETENTION.value
_LEARNING = (_EXPLANATION, _APPLICATION, _TRANSFER)
_SCHEDULED = frozenset(
    {
        PlantStatus.SPROUTING,
        PlantStatus.INDEPENDENT,
        PlantStatus.TRANSFER,
        PlantStatus.RETAINED,
    }
)


def rule_version(profile: RulesProfile) -> str:
    """The string stored as `garden_revisions.rule_ver`, e.g. `rules@1+normal.1`."""
    return f"rules@{ENGINE_VERSION}+{profile.name}.{profile.version}"


# ── Status ──
def earned_stage(plant: PlantState, profile: RulesProfile) -> PlantStatus:
    """The stage the scores earn, ignoring time. Only independent tracks climb the ladder."""
    t = profile.reach_threshold

    def reached(dimension: str) -> bool:
        return plant.dimension(dimension).independent >= t

    if reached(_RETENTION):
        return PlantStatus.RETAINED
    if reached(_TRANSFER):
        return PlantStatus.TRANSFER
    if reached(_APPLICATION):
        return PlantStatus.INDEPENDENT
    if reached(_EXPLANATION):
        return PlantStatus.SPROUTING
    if any(plant.dimension(d).assisted >= t for d in GROWTH_DIMENSIONS):
        return PlantStatus.ASSISTED
    return PlantStatus.UNASSESSED


def status_at(plant: PlantState, now: datetime, profile: RulesProfile) -> PlantStatus:
    """Earned stage, overlaid with DUE then WILTING once the review is overdue."""
    stage = earned_stage(plant, profile)
    due = plant.next_review_at
    if stage not in _SCHEDULED or due is None or now < due:
        return stage
    if now >= due + timedelta(seconds=profile.wilt_grace_seconds):
        return PlantStatus.WILTING
    return PlantStatus.DUE


def apply_decay(state: GardenState, now: datetime, profile: RulesProfile) -> RulesResult:
    """Time passing alone: propose DUE/WILTING status changes (reason `decay`)."""
    return propose(state, (), now, profile)


# ── Core ──
def propose(
    state: GardenState,
    observations: Iterable[Observation],
    now: datetime,
    profile: RulesProfile,
    *,
    known_concepts: Collection[str] | None = None,
) -> RulesResult:
    """Apply accepted assessments to `state` at time `now`, returning the proposed changes.

    `known_concepts` (the active curriculum's keys) is optional; when given, observations for
    other concepts are skipped.
    """
    if now.tzinfo is None:
        raise ValueError("`now` must be timezone-aware")
    items = list(observations)
    for o in items:
        if o.occurred_at.tzinfo is None:
            raise ValueError(f"`occurred_at` must be timezone-aware (assessment {o.assessment_id})")
    ordered = sorted(items, key=lambda o: (o.occurred_at, str(o.assessment_id)))

    plants = dict(state.plants)
    applied = set(state.applied)
    processed: list[uuid.UUID] = []
    originals: dict[str, PlantState | None] = {}
    events: dict[str, list[GrowthEvent]] = {}
    skipped: list[Skipped] = []
    reassess: list[uuid.UUID] = []
    known = frozenset(known_concepts) if known_concepts is not None else None

    def skip(obs: Observation, reason: SkipReason) -> None:
        skipped.append(Skipped(obs.assessment_id, reason))

    for obs in ordered:
        if obs.assessment_id in applied:
            skip(obs, "duplicate_assessment")
            continue
        if known is not None and obs.concept_key not in known:
            skip(obs, "unknown_concept")
            continue
        rejection = _precheck(obs)
        if rejection is None and _is_ambiguous(obs, profile):
            reassess.append(obs.assessment_id)
            continue
        if rejection is None and _is_out_of_order(plants.get(obs.concept_key), obs):
            skip(obs, "out_of_order")  # not consumed: the caller rebuilds with `replay()`
            continue
        applied.add(obs.assessment_id)
        processed.append(obs.assessment_id)
        if rejection is not None:
            skip(obs, rejection)
            continue

        before = plants.get(obs.concept_key)
        plant = before or PlantState(concept_key=obs.concept_key)
        updated, event, reason = _apply(plant, obs, profile)
        if reason is not None:
            skip(obs, reason)
            continue
        assert event is not None
        originals.setdefault(obs.concept_key, before)
        plants[obs.concept_key] = updated
        events.setdefault(obs.concept_key, []).append(event)

    changes: list[PlantChange] = []
    for key in sorted(plants):
        plant = plants[key]
        status = status_at(plant, now, profile)
        if key in events:
            before = originals[key]
            plants[key] = after = replace(plant, status=status)
            changes.append(
                PlantChange(
                    concept_key=key,
                    reason="assessment",
                    status_before=before.status if before else PlantStatus.UNASSESSED,
                    status_after=status,
                    before=before,
                    after=after,
                    events=tuple(events[key]),
                )
            )
        elif status != plant.status:
            plants[key] = after = replace(plant, status=status)
            changes.append(
                PlantChange(
                    concept_key=key,
                    reason="decay",
                    status_before=plant.status,
                    status_after=status,
                    before=plant,
                    after=after,
                )
            )

    return RulesResult(
        rule_version=rule_version(profile),
        profile_hash=profile.content_hash,
        changes=tuple(changes),
        state=GardenState(plants=plants, applied=frozenset(applied)),
        skipped=tuple(skipped),
        reassess=tuple(reassess),
        processed=tuple(processed),
    )


def replay(
    observations: Iterable[Observation],
    now: datetime,
    profile: RulesProfile,
    *,
    known_concepts: Collection[str] | None = None,
) -> RulesResult:
    """Rebuild a garden from scratch (time travel to a revision: pass its observations and time)."""
    return propose(GardenState(), observations, now, profile, known_concepts=known_concepts)


def due_concepts(state: GardenState, now: datetime, profile: RulesProfile) -> tuple[str, ...]:
    """Concept keys whose review is due or overdue, soonest first (for retention calls)."""
    due = [
        (p.next_review_at, k)
        for k, p in state.plants.items()
        if p.next_review_at is not None
        and status_at(p, now, profile) in (PlantStatus.DUE, PlantStatus.WILTING)
    ]
    return tuple(k for _, k in sorted(due))


# ── Per-observation rules ──
def _precheck(obs: Observation) -> SkipReason | None:
    if not obs.evidence_ids:
        return "no_evidence"
    if obs.dimension not in GROWTH_DIMENSIONS:
        # `communication` (record_observation) is evidence for memory and Vidura's report only.
        return "non_growth_dimension" if obs.dimension == "communication" else "unknown_dimension"
    if obs.outcome is AssessmentOutcome.UNASSESSABLE:
        return "unassessable"
    return None


def _is_ambiguous(obs: Observation, profile: RulesProfile) -> bool:
    u = obs.uncertainty
    return u is not None and (math.isnan(u) or u > profile.max_uncertainty)


def _is_out_of_order(plant: PlantState | None, obs: Observation) -> bool:
    last = plant.last_evidence_at if plant is not None else None
    return last is not None and obs.occurred_at < last


def _apply(
    plant: PlantState, obs: Observation, profile: RulesProfile
) -> tuple[PlantState, GrowthEvent | None, SkipReason | None]:
    t = profile.reach_threshold
    independent = obs.assistance is Assistance.INDEPENDENT
    prefix = "i" if independent else "a"
    dim = obs.dimension
    state = plant.dimension(dim)
    before = state.independent if independent else state.assisted
    credit = profile.outcome_credit[obs.outcome]
    due = plant.next_review_at
    was_due = due is not None and obs.occurred_at >= due

    def event(kind: str, after: float) -> GrowthEvent:
        return GrowthEvent(
            assessment_id=obs.assessment_id,
            evidence_ids=obs.evidence_ids,
            dimension=dim,
            track=obs.assistance,
            kind=kind,  # type: ignore[arg-type]
            before=before,
            after=after,
        )

    step = plant.review_step
    next_review = plant.next_review_at
    intervals = profile.review_intervals_seconds

    if credit <= 0:
        # An independent miss at review time resets the clock; it never lowers a score.
        if independent and was_due:
            step = max(0, step - profile.review_fail_drop)
            next_review = obs.occurred_at + timedelta(seconds=intervals[step])
            updated = replace(
                plant,
                review_step=step,
                next_review_at=next_review,
                last_evidence_at=_latest(plant.last_evidence_at, obs.occurred_at),
            )
            return updated, event("review_failed", before), None
        return plant, None, "no_credit"

    families = state.families
    family_key: str | None = None
    if dim == _RETENTION:
        if not independent:
            return plant, None, "assisted_retention_not_counted"
        if not any(plant.dimension(d).independent >= t for d in (_EXPLANATION, _APPLICATION)):
            return plant, None, "retention_before_learning"
        gap = timedelta(seconds=profile.retention_min_gap_seconds)
        if plant.last_learning_at is None or obs.occurred_at - plant.last_learning_at < gap:
            return plant, None, "retention_too_soon"
    else:
        if dim == _TRANSFER:
            if obs.problem_family is None:
                return plant, None, "missing_problem_family"
            if f"{prefix}:{obs.problem_family}" in plant.dimension(_APPLICATION).families:
                return plant, None, "same_family_as_application"
        family_key = f"{prefix}:{obs.problem_family or obs.assessment_id}"
        if family_key in families:
            return plant, None, "repeat_problem_family"

    after = round(min(1.0, before + credit), 6)
    if after == before and not (independent and was_due):
        return plant, None, "no_credit"

    new_families = tuple(sorted({*families, family_key})) if family_key else families
    new_state = (
        replace(state, independent=after, families=new_families)
        if independent
        else replace(state, assisted=after, families=new_families)
    )
    dims = {**plant.dimensions, dim: new_state}
    updated = replace(
        plant,
        dimensions=dims,
        last_evidence_at=_latest(plant.last_evidence_at, obs.occurred_at),
    )
    if independent:
        if dim in _LEARNING:
            updated = replace(
                updated, last_learning_at=_latest(plant.last_learning_at, obs.occurred_at)
            )
        if next_review is None:
            if earned_stage(updated, profile) in _SCHEDULED:
                step, next_review = 0, obs.occurred_at + timedelta(seconds=intervals[0])
        elif was_due or (dim == _RETENTION and before < t <= after):
            step = min(step + 1, len(intervals) - 1)
            next_review = obs.occurred_at + timedelta(seconds=intervals[step])
        updated = replace(updated, review_step=step, next_review_at=next_review)

    kind = "growth" if after > before else "review_passed"
    return updated, event(kind, after), None


def _latest(current: datetime | None, candidate: datetime) -> datetime:
    return candidate if current is None or candidate > current else current


__all__ = [
    "DimensionState",
    "apply_decay",
    "due_concepts",
    "earned_stage",
    "propose",
    "replay",
    "rule_version",
    "status_at",
]
