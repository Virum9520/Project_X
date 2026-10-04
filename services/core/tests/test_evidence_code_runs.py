"""Arjuna's code_run evidence and Bhima's retention hand-off through the post-call pipeline.

In-memory store, scripted LLM, no database.
"""

import uuid
from datetime import timedelta
from typing import Any

from evidence_fixtures import (
    BS,
    CONV,
    HEAP,
    T0,
    ScriptedLLM,
    World,
    judge_body,
    payload,
    turn,
    verdict,
)

from sg_core.evidence import CodeRun, LLMJudge, PipelineDeps, run_post_call
from sg_core.evidence.code_runs import code_run_verdicts
from sg_core.models.enums import AssessmentOutcome, Assistance, Character
from sg_core.rules import load_profile

NOW = T0 + timedelta(minutes=5)


def deps(world: World, llm: ScriptedLLM) -> PipelineDeps:
    return PipelineDeps(
        store=world.store,
        judge=LLMJudge(llm, "judge-model"),
        profile_for=lambda demo: load_profile("demo" if demo else "normal"),
        clock=lambda: NOW,
    )


def run(
    key: str = BS,
    *,
    passed: int = 5,
    total: int = 5,
    status: str | None = None,
    assistance: Assistance = Assistance.INDEPENDENT,
    hints: int = 0,
    family: str | None = "bs.classic",
    minutes: int = 1,
) -> CodeRun:
    rid = uuid.uuid4()
    return CodeRun(
        concept_key=key,
        status=status or ("passed" if passed == total else "failed"),
        passed=passed,
        total=total,
        assistance=assistance,
        quote=f"Ran the hidden tests: {passed} of {total} passed.",
        occurred_at=T0 + timedelta(minutes=minutes),
        dedupe_key=f"code_run:{rid}",
        problem_family=family,
        hint_count=hints,
        run_id=rid,
    )


async def arjuna(*runs: CodeRun) -> World:
    world = World(Character.ARJUNA, "technical_interview")
    sid = await world.start_session()
    for r in runs:
        world.store.seed_code_run(sid, world.user_id, r)
    return world


def plant(world: World, key: str = BS) -> Any:
    return world.store.plants[world.user_id][key]


async def test_independent_passing_run_grows_application_with_no_transcript() -> None:
    world = await arjuna(run())
    llm = ScriptedLLM(judge_body())
    result = await run_post_call(deps(world, llm), payload([], focus=None))
    assert result.status == "judged" and result.revision == 1 and result.assessments == 1
    assert llm.calls == []  # tests are deterministic: no judge call, no spend
    app = plant(world).dimension("application")
    assert app.independent > 0 and app.assisted == 0
    # Every growth event cites evidence, and the evidence is the stored code run.
    [assessment] = world.store.assessments.values()
    assert assessment.item.judge_model == "rules:code_run@1"
    cited = [world.store.evidence[i].item for i in assessment.evidence_ids]
    assert [e.kind for e in cited] == ["code_run"]
    events = [e for c in world.store.revisions[0]["changes"] for e in c["events"]]
    assert events and all(e["evidence_ids"] for e in events)


async def test_hinted_run_is_assisted_and_never_credits_the_independent_track() -> None:
    world = await arjuna(run(hints=2, assistance=Assistance.ASSISTED))
    await run_post_call(deps(world, ScriptedLLM(judge_body())), payload([], focus=None))
    app = plant(world).dimension("application")
    assert app.assisted > 0 and app.independent == 0


async def test_a_hint_on_the_run_raises_assistance_even_if_the_row_says_independent() -> None:
    [v] = code_run_verdicts([run(hints=1)], World().store._catalog)
    assert v.assistance is Assistance.ASSISTED


async def test_failed_and_errored_runs_never_grow_anything() -> None:
    world = await arjuna(run(passed=0, total=5), run(status="timeout", passed=0, total=0))
    result = await run_post_call(deps(world, ScriptedLLM(judge_body())), payload([], focus=None))
    assert result.revision is None
    assert BS not in world.store.plants.get(world.user_id, {})


def test_outcomes_and_choice_of_the_run_that_counts() -> None:
    catalog = World().store._catalog
    partial = run(passed=3, total=5, minutes=1)
    assisted_full = run(hints=1, assistance=Assistance.ASSISTED, minutes=2, family="bs.other")
    independent_partial = partial
    [v] = code_run_verdicts([assisted_full, independent_partial], catalog)
    # The independent run that earned credit wins over an assisted full pass.
    assert v.outcome is AssessmentOutcome.PARTIAL and v.assistance is Assistance.INDEPENDENT
    assert v.code_run is independent_partial
    [w] = code_run_verdicts([run(passed=0), run(passed=5, minutes=3)], catalog)
    assert w.outcome is AssessmentOutcome.DEMONSTRATED
    assert code_run_verdicts([run("nope.unknown")], catalog) == []


async def test_judge_cannot_also_grade_application_for_a_code_run_concept() -> None:
    world = await arjuna(run())
    turns = [
        turn("agent", "Walk me through your solution.", 0),
        turn("user", "I used two pointers and it is a linear scan overall.", 10),
    ]
    llm = ScriptedLLM(
        judge_body(
            verdict(dimension="application", turn=1, quote="I used two pointers"),
            verdict(dimension="explanation", turn=1, quote="linear scan overall"),
        )
    )
    result = await run_post_call(deps(world, llm), payload(turns, focus=BS))
    assert [r.reason for r in result.rejected] == ["code_run_decides_application"]
    dims = sorted(a.item.dimension for a in world.store.assessments.values())
    assert dims == ["application", "explanation"]
    [app] = [a for a in world.store.assessments.values() if a.item.dimension == "application"]
    assert app.item.judge_model == "rules:code_run@1"


async def test_replay_is_a_noop_and_a_new_run_adds_a_correction_revision() -> None:
    first = run(passed=3, total=5, minutes=1)
    world = await arjuna(first)
    data = payload([], focus=None)
    one = await run_post_call(deps(world, ScriptedLLM(judge_body())), data)
    again = await run_post_call(deps(world, ScriptedLLM(judge_body())), data)
    assert one.revision == 1 and again.status == "unchanged"
    sid = world.session_id
    assert sid is not None
    world.store.seed_code_run(sid, world.user_id, run(minutes=3, family="bs.other"))
    third = await run_post_call(deps(world, ScriptedLLM(judge_body())), data)
    assert third.status == "judged"
    statuses = sorted(a.status.value for a in world.store.assessments.values())
    assert statuses == ["accepted", "superseded"]
    assert world.store.revisions[-1]["reason"] == "correction"


async def test_code_run_for_a_concept_outside_the_catalog_is_ignored() -> None:
    world = await arjuna(run("nope.unknown"))
    result = await run_post_call(deps(world, ScriptedLLM(judge_body())), payload([], focus=None))
    assert result.status == "empty_transcript"


# ── Bhima: the retention answer becomes evidence, and the result is recorded ──
async def _bhima(learned: bool = True) -> World:
    world = World(Character.BHIMA, "accountability_call")
    await world.start_session()
    world.store.retention[CONV] = BS
    if learned:
        from test_evidence_pipeline import _seed_learned

        await _seed_learned(world, minutes_ago=60 * 24 * 2)
    return world


def _results(world: World) -> list[Any]:
    return [m.new for m in world.store.memories.values() if m.new.kind == "retention_result"]


async def test_retention_answer_becomes_evidence_and_a_result_memory() -> None:
    world = await _bhima()
    turns = [
        turn("agent", "Quick one: what makes binary search O(log n)?", 100),
        turn("user", "Each comparison halves what is left, so log n steps.", 110),
    ]
    llm = ScriptedLLM(
        judge_body(
            verdict(dimension="retention", turn=1, quote="Each comparison halves what is left")
        )
    )
    result = await run_post_call(deps(world, llm), payload(turns, focus=None))
    assert result.revision is not None
    [mem] = _results(world)
    assert mem.data["answered"] is True and mem.data["counted"] is True
    assert mem.data["concept_key"] == BS and mem.evidence_ids
    assert [e for _, t, e in world.store.events if t == "bhima.retention_judged"]


async def test_assisted_or_uncounted_retention_is_recorded_as_not_counted() -> None:
    world = await _bhima(learned=False)
    turns = [turn("user", "Each comparison halves what is left, so log n steps.", 110)]
    llm = ScriptedLLM(
        judge_body(verdict(dimension="retention", turn=0, quote="Each comparison halves"))
    )
    await run_post_call(deps(world, llm), payload(turns, focus=None))
    [mem] = _results(world)
    assert mem.data["answered"] is True and mem.data["counted"] is False
    assert mem.data["skip_reason"] == "retention_before_learning"


async def test_unanswered_retention_question_changes_nothing_and_is_recorded() -> None:
    world = await _bhima()
    turns = [
        turn("agent", "Quick one: what makes binary search O(log n)?", 100),
        turn("user", "Sorry, I have to run, can we skip it?", 110),
    ]
    llm = ScriptedLLM(judge_body())
    result = await run_post_call(deps(world, llm), payload(turns, focus=None))
    assert result.revision is None
    [mem] = _results(world)
    assert mem.data["answered"] is False and mem.data["outcome"] == "no_answer"
    assert not mem.evidence_ids


async def test_no_retention_question_means_no_result_memory() -> None:
    world = World(Character.BHIMA, "accountability_call")
    await world.start_session()
    turns = [turn("user", "I did my practice problems today.", 10)]
    await run_post_call(deps(world, ScriptedLLM(judge_body())), payload(turns, focus=None))
    assert _results(world) == []
    assert HEAP not in world.store.plants.get(world.user_id, {})
