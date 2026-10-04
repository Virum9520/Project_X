import json
from pathlib import Path

import pytest
import yaml
from arjuna_fixtures import local_sandbox, reference_solution

from sg_api.arjuna.harness import MAX_CODE_BYTES, build_run
from sg_api.arjuna.problems import (
    ALL_PROBLEMS,
    BY_ID,
    MAX_HINT_LEVEL,
    SUPPORTED_LANGUAGES,
    camel,
    cases_for,
    problems_for_concept,
    public_examples,
    select_problem,
    starter_code,
)
from sg_api.arjuna.runner import run_problem_tests

CURRICULUM = Path(__file__).resolve().parents[3] / "curriculum" / "cs-core" / "v1" / "concepts"


def _curriculum_keys() -> set[str]:
    keys: set[str] = set()
    for path in CURRICULUM.glob("*.yaml"):
        data = yaml.safe_load(path.read_text())
        keys |= {c["key"] for c in data["concepts"]}
    return keys


def test_ids_are_unique_and_well_formed() -> None:
    assert len({p.id for p in ALL_PROBLEMS}) == len(ALL_PROBLEMS)
    for p in ALL_PROBLEMS:
        assert p.id.startswith("p_")
        assert p.function.isidentifier() and p.js_function.isidentifier()


def test_every_problem_maps_to_a_real_curriculum_concept() -> None:
    keys = _curriculum_keys()
    for p in ALL_PROBLEMS:
        assert p.concept_key in keys, p.id
        assert set(p.secondary_concepts) <= keys, p.id


def test_hints_escalate_and_never_contain_code_blocks() -> None:
    for p in ALL_PROBLEMS:
        assert len(p.hints) == MAX_HINT_LEVEL
        assert all(h.strip() and "```" not in h for h in p.hints)


def test_only_examples_are_shareable_and_hidden_cases_are_labelled() -> None:
    for p in ALL_PROBLEMS:
        assert len(p.examples) >= 2 and all(c.shareable for c in p.examples), p.id
        assert len(p.hidden) >= 3 and not any(c.shareable for c in p.hidden), p.id
        assert all(c.label for c in (*p.examples, *p.hidden))
        assert any("large" in c.label for c in p.hidden), f"{p.id} has no performance case"


def test_expected_values_are_json_and_arguments_match_the_signature() -> None:
    for p in ALL_PROBLEMS:
        for c in cases_for(p.id):
            assert len(c.args) == len(p.params), (p.id, c.label)
            json.dumps(c.args)
            json.dumps(c.expected)


def test_reference_does_not_mutate_cached_cases() -> None:
    before = json.dumps([c.args for c in cases_for("p_merge_intervals")])
    cases_for.cache_clear()
    assert json.dumps([c.args for c in cases_for("p_merge_intervals")]) == before


def test_public_examples_expose_inputs_but_never_hidden_cases() -> None:
    for p in ALL_PROBLEMS:
        shown = public_examples(p)
        assert len(shown) == len(p.examples)
        assert all(set(e["input"]) == set(p.params) for e in shown)


def test_starter_code_has_the_right_function_name() -> None:
    p = BY_ID["p_two_sum"]
    assert "def two_sum(nums, target):" in starter_code(p, "python")
    assert "function twoSum(nums, target)" in starter_code(p, "javascript")
    ts = starter_code(p, "typescript")
    assert "function twoSum(nums: any, target: any): any" in ts
    assert camel("length_of_longest_substring") == "lengthOfLongestSubstring"


def test_selection_prefers_the_concept_then_a_new_family() -> None:
    first, matched = select_problem("dsa.heaps")
    assert matched and first.concept_key == "dsa.heaps"
    second, _ = select_problem(
        "dsa.dfs", exclude={"p_number_of_islands"}, exclude_families={"flood_fill_components"}
    )
    assert second.id != "p_number_of_islands"  # a related concept's problem, in a new family


def test_selection_falls_back_to_fundamentals_for_unknown_concepts() -> None:
    problem, matched = select_problem("os.deadlocks")
    assert not matched and problem.difficulty == 1
    problem, matched = select_problem(None, difficulty="harder")
    assert not matched and problem.difficulty == 3


def test_selection_repeats_only_when_everything_was_used() -> None:
    used = {p.id for p in problems_for_concept("dsa.heaps")}
    problem, _ = select_problem("dsa.heaps", exclude=used)
    assert problem.id in used


def test_build_run_rejects_unsupported_and_oversized() -> None:
    p = BY_ID["p_two_sum"]
    with pytest.raises(ValueError, match="not available"):
        build_run(p, "java", "class A {}")
    with pytest.raises(ValueError, match="too large"):
        build_run(p, "python", "x" * (MAX_CODE_BYTES + 1))
    assert set(SUPPORTED_LANGUAGES) == {"python", "javascript", "typescript"}


@pytest.mark.parametrize("problem_id", sorted(BY_ID))
async def test_the_reference_passes_every_problem_through_the_real_harness(
    problem_id: str,
) -> None:
    sandbox, backend = local_sandbox()
    report = await run_problem_tests(
        sandbox, BY_ID[problem_id], "python", reference_solution(problem_id)
    )
    assert report.status == "passed", report.summary
    assert report.passed == report.total == len(cases_for(problem_id))
    assert backend.created == backend.killed == 1
