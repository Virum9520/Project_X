"""Garden rules engine: scenarios plus seeded property-style checks (no database, no clock)."""

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from sg_core.curriculum import curriculum_path, load_curriculum
from sg_core.models.enums import AssessmentOutcome, Assistance, PlantStatus
from sg_core.rules import (
    GardenState,
    Observation,
    PlantState,
    RulesProfile,
    RulesProfileError,
    apply_decay,
    due_concepts,
    load_profile,
    propose,
    replay,
    rule_version,
)

T0 = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
CONCEPT = "dsa.binary-search"
D, P, N = (
    AssessmentOutcome.DEMONSTRATED,
    AssessmentOutcome.PARTIAL,
    AssessmentOutcome.NOT_DEMONSTRATED,
)
IND, AST = Assistance.INDEPENDENT, Assistance.ASSISTED


def minutes(m: float) -> datetime:
    return T0 + timedelta(minutes=m)


def obs(
    dimension: str,
    at: datetime,
    *,
    outcome: AssessmentOutcome = D,
    assistance: Assistance = IND,
    family: str | None = None,
    concept: str = CONCEPT,
    uncertainty: float | None = None,
    evidence: bool = True,
    seed: int | None = None,
) -> Observation:
    rng = random.Random(seed) if seed is not None else None
    make = (lambda: uuid.UUID(int=rng.getrandbits(128), version=4)) if rng else uuid.uuid4
    return Observation(
        assessment_id=make(),
        concept_key=concept,
        dimension=dimension,
        outcome=outcome,
        assistance=assistance,
        occurred_at=at,
        evidence_ids=(make(),) if evidence else (),
        uncertainty=uncertainty,
        problem_family=family,
    )


@pytest.fixture(scope="module")
def normal() -> RulesProfile:
    return load_profile("normal")


@pytest.fixture(scope="module")
def demo() -> RulesProfile:
    return load_profile("demo")


def status(result_state: GardenState, concept: str = CONCEPT) -> PlantStatus:
    return result_state.plants[concept].status


# ── Profiles ──
def test_profiles_load_and_are_versioned(normal: RulesProfile, demo: RulesProfile) -> None:
    assert rule_version(normal) == "rules@1+normal.1"
    assert rule_version(demo) == "rules@1+demo.1"
    assert normal.content_hash != demo.content_hash


def test_demo_profile_only_compresses_the_clock(normal: RulesProfile, demo: RulesProfile) -> None:
    clock = {
        "name",
        "retention_min_gap_seconds",
        "review_intervals_seconds",
        "wilt_grace_seconds",
    }
    a, b = normal.model_dump(), demo.model_dump()
    assert {k for k in a if a[k] != b[k]} <= clock
    assert max(demo.review_intervals_seconds) < min(normal.review_intervals_seconds)


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(RulesProfileError):
        load_profile("turbo")


def test_profile_rejects_bad_numbers(normal: RulesProfile) -> None:
    data = normal.model_dump()
    data["outcome_credit"] = {**data["outcome_credit"], AssessmentOutcome.DEMONSTRATED: 0.1}
    with pytest.raises(ValueError, match="reach_threshold"):
        RulesProfile.model_validate(data)


@pytest.mark.parametrize(
    ("partial", "missed", "match"),
    [(0.5, 0.7, "not_demonstrated"), (0.5, 0.1, "not_demonstrated"), (1.0, 0.0, "partial")],
)
def test_profile_never_credits_failures(
    normal: RulesProfile, partial: float, missed: float, match: str
) -> None:
    data = normal.model_dump()
    data["outcome_credit"] = {D: 0.9, P: partial, N: missed}
    with pytest.raises(ValueError, match=match):
        RulesProfile.model_validate(data)


# ── Growth ladder: every stage within one session ──
def session(demo_clock: bool = False) -> list[Observation]:
    return [
        obs("explanation", minutes(1), family="teach-back"),
        obs("application", minutes(3), family="two-pointers"),
        obs("transfer", minutes(6), family="graph-bfs"),
        obs("retention", minutes(12)),
    ]


def test_one_session_reaches_every_stage(normal: RulesProfile) -> None:
    state = GardenState()
    expected = [
        PlantStatus.SPROUTING,
        PlantStatus.INDEPENDENT,
        PlantStatus.TRANSFER,
        PlantStatus.RETAINED,
    ]
    for o, stage in zip(session(), expected, strict=True):
        result = propose(state, [o], o.occurred_at, normal)
        state = result.state
        assert status(state) is stage
        (change,) = result.changes
        assert change.events[0].evidence_ids == o.evidence_ids  # cited
        assert result.rule_version == "rules@1+normal.1"
    assert state.plants[CONCEPT].dimension("retention").independent == 1.0


def test_retention_needs_a_later_recall(normal: RulesProfile) -> None:
    early = [obs("explanation", minutes(1), family="f"), obs("retention", minutes(2))]
    result = replay(early, minutes(2), normal)
    assert status(result.state) is PlantStatus.SPROUTING
    assert [s.reason for s in result.skipped] == ["retention_too_soon"]


def test_demo_profile_allows_retention_in_seconds(demo: RulesProfile) -> None:
    items = [obs("explanation", minutes(1), family="f"), obs("retention", minutes(2))]
    assert status(replay(items, minutes(2), demo).state) is PlantStatus.RETAINED


def test_retention_before_learning_is_ignored(normal: RulesProfile) -> None:
    result = replay([obs("retention", minutes(30))], minutes(30), normal)
    assert [s.reason for s in result.skipped] == ["retention_before_learning"]
    assert not result.changes


def test_partial_needs_two_to_reach(normal: RulesProfile) -> None:
    first = propose(
        GardenState(), [obs("explanation", minutes(1), outcome=P, family="a")], minutes(1), normal
    )
    assert first.state.plants[CONCEPT].status is PlantStatus.UNASSESSED
    second = propose(
        first.state, [obs("explanation", minutes(2), outcome=P, family="b")], minutes(2), normal
    )
    assert status(second.state) is PlantStatus.SPROUTING


# ── Assisted vs independent ──
def test_assisted_evidence_never_advances_past_assisted(normal: RulesProfile) -> None:
    items = [
        obs(d, minutes(i), assistance=AST, family=f"f{i}")
        for i, d in enumerate(["explanation", "application", "transfer"], start=1)
    ]
    state = replay(items, minutes(5), normal).state
    plant = state.plants[CONCEPT]
    assert plant.status is PlantStatus.ASSISTED
    assert all(plant.dimension(d).independent == 0 for d in plant.dimensions)
    assert plant.next_review_at is None  # assisted growth never schedules or wilts


def test_assisted_tracks_do_not_feed_independent(normal: RulesProfile) -> None:
    items = [
        obs("explanation", minutes(1), assistance=AST, family="a"),
        obs("explanation", minutes(2), assistance=IND, family="b"),
    ]
    plant = replay(items, minutes(3), normal).state.plants[CONCEPT]
    dim = plant.dimension("explanation")
    assert (dim.independent, dim.assisted) == (1.0, 1.0)
    assert plant.status is PlantStatus.SPROUTING


def test_assisted_retention_does_not_count(normal: RulesProfile) -> None:
    items = [
        obs("explanation", minutes(1), family="f"),
        obs("retention", minutes(30), assistance=AST),
    ]
    result = replay(items, minutes(30), normal)
    assert status(result.state) is PlantStatus.SPROUTING
    assert result.skipped[0].reason == "assisted_retention_not_counted"


# ── Problem families ──
def test_repeat_family_counts_once(normal: RulesProfile) -> None:
    items = [
        obs("application", minutes(1), outcome=P, family="x"),
        obs("application", minutes(2), outcome=P, family="x"),
    ]
    result = replay(items, minutes(3), normal)
    assert result.state.plants[CONCEPT].dimension("application").independent == 0.5
    assert [s.reason for s in result.skipped] == ["repeat_problem_family"]


def test_transfer_needs_a_different_family(normal: RulesProfile) -> None:
    items = [
        obs("application", minutes(1), family="x"),
        obs("transfer", minutes(2), family="x"),
        obs("transfer", minutes(3)),
    ]
    result = replay(items, minutes(4), normal)
    assert status(result.state) is PlantStatus.INDEPENDENT
    assert [s.reason for s in result.skipped] == [
        "same_family_as_application",
        "missing_problem_family",
    ]
    assert (
        status(replay([*items, obs("transfer", minutes(5), family="y")], minutes(6), normal).state)
        is PlantStatus.TRANSFER
    )


# ── Citations, ambiguity, dimensions ──
def test_growth_without_evidence_is_refused(normal: RulesProfile) -> None:
    result = replay([obs("explanation", minutes(1), evidence=False)], minutes(1), normal)
    assert not result.changes
    assert result.skipped[0].reason == "no_evidence"


def test_ambiguous_evidence_is_flagged_not_grown(normal: RulesProfile) -> None:
    o = obs("explanation", minutes(1), uncertainty=0.8)
    result = replay([o], minutes(1), normal)
    assert result.reassess == (o.assessment_id,)
    assert not result.changes
    assert o.assessment_id not in result.state.applied
    assert propose(result.state, [o], minutes(1), normal).reassess == (o.assessment_id,)


def test_nan_uncertainty_is_ambiguous(normal: RulesProfile) -> None:
    o = obs("explanation", minutes(1), uncertainty=float("nan"))
    result = replay([o], minutes(1), normal)
    assert result.reassess == (o.assessment_id,)
    assert not result.changes and o.assessment_id not in result.state.applied


def test_communication_never_grows_a_plant(normal: RulesProfile) -> None:
    result = replay(
        [obs("communication", minutes(1), concept="behavioral.star-method")], minutes(1), normal
    )
    assert not result.changes and not result.state.plants
    assert result.skipped[0].reason == "non_growth_dimension"
    unknown = replay([obs("vibes", minutes(1))], minutes(1), normal)
    assert unknown.skipped[0].reason == "unknown_dimension"


def test_unassessable_and_misses_do_nothing(normal: RulesProfile) -> None:
    items = [
        obs("explanation", minutes(1), outcome=AssessmentOutcome.UNASSESSABLE),
        obs("application", minutes(2), outcome=N),
    ]
    result = replay(items, minutes(3), normal)
    assert not result.changes
    assert [s.reason for s in result.skipped] == ["unassessable", "no_credit"]


def test_unknown_concepts_are_skipped_against_the_curriculum(normal: RulesProfile) -> None:
    spec = load_curriculum(curriculum_path("cs-core", "v1"))
    keys = {c.key for c in spec.concepts}
    good = next(k for k in sorted(keys) if k.startswith("dsa."))
    items = [
        obs("explanation", minutes(1), concept=good, family="a"),
        obs("explanation", minutes(2), concept="dsa.not-a-thing", family="b"),
    ]
    result = replay(items, minutes(3), normal, known_concepts=keys)
    assert set(result.state.plants) == {good}
    assert result.skipped[0].reason == "unknown_concept"


# ── Idempotency and determinism ──
def test_duplicates_are_noops(normal: RulesProfile) -> None:
    o = obs("explanation", minutes(1), family="a")
    once = propose(GardenState(), [o], minutes(1), normal)
    again = propose(once.state, [o], minutes(2), normal)
    assert not again.changes and again.state == once.state
    assert [s.reason for s in again.skipped] == ["duplicate_assessment"]
    twice = replay([o, o], minutes(1), normal)
    assert twice.state == once.state


def random_observations(seed: int, n: int = 30) -> list[Observation]:
    rng = random.Random(seed)
    dims = ["explanation", "application", "transfer", "retention", "communication"]
    families = [None, "a", "b", "c", "d"]
    out = []
    for i in range(n):
        out.append(
            obs(
                rng.choice(dims),
                T0 + timedelta(minutes=rng.randint(0, 600)),
                outcome=rng.choice([D, D, P, N, AssessmentOutcome.UNASSESSABLE]),
                assistance=rng.choice([IND, IND, AST]),
                family=rng.choice(families),
                concept=rng.choice(["dsa.binary-search", "os.paging", "networks.tcp"]),
                uncertainty=rng.choice([None, None, 0.1, 0.9]),
                evidence=rng.random() > 0.05,
                seed=seed * 1000 + i,
            )
        )
    return out


@pytest.mark.parametrize("seed", range(40))
def test_replay_is_deterministic_and_order_independent(normal: RulesProfile, seed: int) -> None:
    items = random_observations(seed)
    now = T0 + timedelta(days=2)
    base = replay(items, now, normal)
    shuffled = items[:]
    random.Random(seed + 1).shuffle(shuffled)
    assert replay(shuffled, now, normal) == base
    assert replay(items, now, normal) == base
    # Every growth event cites evidence, and nothing ambiguous or communicative grew.
    for change in base.changes:
        assert all(e.evidence_ids for e in change.events)
    assert base.to_revision_changes() == replay(items, now, normal).to_revision_changes()


@pytest.mark.parametrize("seed", range(40))
def test_batching_matches_one_shot_replay(normal: RulesProfile, seed: int) -> None:
    items = sorted(random_observations(seed), key=lambda o: (o.occurred_at, str(o.assessment_id)))
    now = T0 + timedelta(days=2)
    state = GardenState()
    for chunk in (items[:10], items[10:20], items[20:]):
        state = propose(state, chunk, now, normal).state
    one_shot = replay(items, now, normal).state
    assert state.plants == one_shot.plants
    assert state.applied == one_shot.applied


def test_out_of_order_evidence_is_not_applied_incrementally(normal: RulesProfile) -> None:
    explain = obs("explanation", minutes(0), family="teach-back")
    recall = obs("retention", minutes(10))
    late = obs("application", minutes(9), family="two-pointers")
    state = propose(GardenState(), [explain, recall], minutes(10), normal).state
    result = propose(state, [late], minutes(11), normal)
    assert [(s.assessment_id, s.reason) for s in result.skipped] == [
        (late.assessment_id, "out_of_order")
    ]
    assert not result.changes and result.state == state
    assert late.assessment_id not in result.state.applied and not result.processed
    # Replay of all three applies them in time order (so the recall is now too soon after the
    # application), and is unaffected by the incremental skip.
    full = replay([explain, recall, late], minutes(11), normal)
    assert [(s.assessment_id, s.reason) for s in full.skipped] == [
        (recall.assessment_id, "retention_too_soon")
    ]
    assert full.state == replay([late, recall, explain], minutes(11), normal).state
    assert full.state.plants[CONCEPT].dimension("application").independent == 1.0


@pytest.mark.parametrize("profile_name", ["normal", "demo"])
@pytest.mark.parametrize("seed", range(25))
def test_scores_are_monotonic_and_assisted_never_leaks(profile_name: str, seed: int) -> None:
    profile = load_profile(profile_name)
    items = sorted(
        random_observations(seed, 40), key=lambda o: (o.occurred_at, str(o.assessment_id))
    )
    state = GardenState()
    previous: dict[str, PlantState] = {}
    for o in items:
        state = propose(state, [o], o.occurred_at, profile).state
        for key, plant in state.plants.items():
            if key in previous:
                for dim, before in previous[key].dimensions.items():
                    after = plant.dimension(dim)
                    assert after.independent >= before.independent
                    assert after.assisted >= before.assisted
        previous = dict(state.plants)
    # Independent scores equal what independent-only evidence produces on its own.
    only_independent = [o for o in items if o.assistance is IND]
    indep = replay(only_independent, T0 + timedelta(days=2), profile).state
    for key, plant in state.plants.items():
        for dim in plant.dimensions:
            expected = indep.plants[key].dimension(dim).independent if key in indep.plants else 0
            assert plant.dimension(dim).independent == expected


# ── Decay and review ──
def test_overdue_review_goes_due_then_wilting_then_recovers(normal: RulesProfile) -> None:
    learned = replay([obs("explanation", minutes(0), family="f")], minutes(0), normal).state
    due_at = learned.plants[CONCEPT].next_review_at
    assert due_at == minutes(0) + timedelta(days=1)
    assert status(learned) is PlantStatus.SPROUTING

    due = apply_decay(learned, due_at, normal)
    assert status(due.state) is PlantStatus.DUE and due.revision_reason == "decay"
    assert due_concepts(due.state, due_at, normal) == (CONCEPT,)

    late = due_at + timedelta(seconds=normal.wilt_grace_seconds)
    wilting = apply_decay(due.state, late, normal)
    assert status(wilting.state) is PlantStatus.WILTING
    assert apply_decay(wilting.state, late, normal).changes == ()  # settled: no churn

    # Decay never lowers a score.
    assert wilting.state.plants[CONCEPT].dimension("explanation").independent == 1.0

    # A successful review (new family) clears wilting and pushes the next review out.
    review = obs("explanation", late + timedelta(minutes=1), family="again")
    healed = propose(wilting.state, [review], review.occurred_at, normal)
    plant = healed.state.plants[CONCEPT]
    assert plant.status is PlantStatus.SPROUTING
    assert plant.review_step == 1
    assert plant.next_review_at == review.occurred_at + timedelta(
        seconds=normal.review_intervals_seconds[1]
    )
    assert healed.changes[0].events[0].kind == "review_passed"


def test_failed_review_resets_the_clock_not_the_score(normal: RulesProfile) -> None:
    items = [obs("explanation", minutes(0), family="f"), obs("application", minutes(2), family="g")]
    state = replay(items, minutes(2), normal).state
    due_at = state.plants[CONCEPT].next_review_at
    assert due_at is not None
    miss = obs("application", due_at + timedelta(hours=1), outcome=N, family="h")
    result = propose(state, [miss], miss.occurred_at, normal)
    plant = result.state.plants[CONCEPT]
    assert plant.dimension("application").independent == 1.0
    assert plant.review_step == 0
    assert plant.next_review_at == miss.occurred_at + timedelta(
        seconds=normal.review_intervals_seconds[0]
    )
    assert result.changes[0].events[0].kind == "review_failed"


def test_assisted_evidence_does_not_postpone_or_clear_a_review(normal: RulesProfile) -> None:
    state = replay([obs("explanation", minutes(0), family="f")], minutes(0), normal).state
    due_at = state.plants[CONCEPT].next_review_at
    assert due_at is not None
    ghost = obs("explanation", due_at + timedelta(minutes=5), assistance=AST, family="g")
    after = propose(state, [ghost], ghost.occurred_at, normal)
    assert after.state.plants[CONCEPT].next_review_at == due_at
    assert status(after.state) is PlantStatus.DUE


def test_decay_is_monotonic_in_time(normal: RulesProfile) -> None:
    state = replay(session(), minutes(12), normal).state
    order = [PlantStatus.RETAINED, PlantStatus.DUE, PlantStatus.WILTING]
    last = -1
    for hours in range(0, 24 * 40, 6):
        now = minutes(12) + timedelta(hours=hours)
        rank = order.index(apply_decay(state, now, normal).state.plants[CONCEPT].status)
        assert rank >= last
        last = rank


def test_demo_clock_wilts_within_minutes(demo: RulesProfile) -> None:
    state = replay([obs("explanation", minutes(0), family="f")], minutes(0), demo).state
    assert status(apply_decay(state, minutes(3), demo).state) is PlantStatus.DUE
    assert status(apply_decay(state, minutes(5), demo).state) is PlantStatus.WILTING


def test_naive_now_is_rejected(normal: RulesProfile) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        propose(GardenState(), [], datetime(2026, 1, 1), normal)


def test_naive_occurred_at_is_rejected(normal: RulesProfile) -> None:
    items = [obs("explanation", minutes(1)), obs("explanation", datetime(2026, 1, 1))]
    with pytest.raises(ValueError, match="`occurred_at` must be timezone-aware"):
        propose(GardenState(), items, minutes(2), normal)


# ── Persistence shape ──
def test_plant_state_round_trips_through_row_json(normal: RulesProfile) -> None:
    state = replay(session(), minutes(12), normal).state
    plant = state.plants[CONCEPT]
    row = PlantState.from_row(
        CONCEPT,
        status=plant.status,
        dimension_scores=plant.to_scores(),
        last_evidence_at=plant.last_evidence_at,
        next_review_at=plant.next_review_at,
    )
    assert row == plant


def test_revision_changes_cite_assessments_and_evidence(normal: RulesProfile) -> None:
    items = session()
    result = replay(items, minutes(12), normal)
    assert set(result.assessment_ids) == {o.assessment_id for o in items}
    (change,) = result.to_revision_changes()
    cited = {e["assessment_id"] for e in change["events"]}
    assert cited == {str(o.assessment_id) for o in items}
    assert all(e["evidence_ids"] for e in change["events"])
    assert result.revision_reason == "assessment"
