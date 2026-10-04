"""The sandbox harness and report, with a local subprocess standing in for E2B."""

import dataclasses
import json

import pytest
from arjuna_fixtures import local_sandbox, node_available

from sg_api.arjuna.problems import BY_ID
from sg_api.arjuna.runner import run_problem_tests

TWO_SUM = BY_ID["p_two_sum"]
PY_GOOD = """
def two_sum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
        seen[n] = i
"""
JS_GOOD = """
function twoSum(nums, target) {
  const seen = new Map();
  for (let i = 0; i < nums.length; i++) {
    if (seen.has(target - nums[i])) return [seen.get(target - nums[i]), i];
    seen.set(nums[i], i);
  }
}
"""


async def _run(
    code: str,
    language: str = "python",
    problem: str = "p_two_sum",
    *,
    limit: float | None = None,
    **kw: object,
):
    sandbox, backend = local_sandbox()
    chosen = BY_ID[problem]
    if limit is not None:
        chosen = dataclasses.replace(chosen, time_limit_s=limit)
    report = await run_problem_tests(sandbox, chosen, language, code, **kw)  # type: ignore[arg-type]
    assert backend.created == backend.killed == 1  # a fresh sandbox, always cleaned up
    return report


async def test_a_correct_solution_passes_everything() -> None:
    report = await _run(PY_GOOD)
    assert report.ok and report.passed == report.total and report.failures == ()
    assert report.summary == f"All {report.total} tests passed."


async def test_wrong_answer_names_the_case_without_leaking_hidden_inputs() -> None:
    # Passes the examples but fails on duplicates and negatives: it assumes distinct positives.
    code = """
def two_sum(nums, target):
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            if nums[i] + nums[j] == target and nums[i] > 0 and nums[j] > 0 and nums[i] != nums[j]:
                return [i, j]
    return []
"""
    report = await _run(code)
    assert report.status in ("failed", "timeout")
    first = report.first_failure
    assert first is not None and first.label == "duplicate values" and not first.shareable
    assert first.input is None and first.expected is None and first.actual is None
    blob = json.dumps(report.summary)
    assert "[3, 3]" not in blob and "duplicate values" in blob


async def test_failing_public_example_shares_input_expected_and_actual() -> None:
    code = "def two_sum(nums, target):\n    return [0, 0]\n"
    report = await _run(code)
    first = report.first_failure
    assert first is not None and first.shareable and first.label == "example 1"
    assert first.input == {"nums": [2, 7, 11, 15], "target": 9}
    assert first.expected == [0, 1] and first.actual == "[0, 0]"


async def test_runtime_error_is_reported_with_the_exception() -> None:
    report = await _run("def two_sum(nums, target):\n    return nums[10**9]\n")
    assert report.status == "error"
    assert report.first_failure is not None
    assert "IndexError" in (report.first_failure.detail or "")


async def test_syntax_error_and_missing_function_are_errors_not_crashes() -> None:
    syntax = await _run("def two_sum(:\n")
    assert syntax.status == "error" and syntax.passed == 0
    missing = await _run("def other():\n    pass\n")
    assert missing.status == "error"
    assert "two_sum is not defined" in (missing.first_failure.detail or "")


async def test_an_infinite_loop_times_out_per_case_and_the_run_still_finishes() -> None:
    report = await _run("def two_sum(nums, target):\n    while True:\n        pass\n", limit=0.4)
    assert report.status == "timeout"
    assert report.passed == 0
    assert report.first_failure is not None and report.first_failure.kind == "timeout"


async def test_learner_output_cannot_forge_a_pass() -> None:
    code = (
        "import sys, json\n"
        "def two_sum(nums, target):\n"
        "    print('SG_RESULT deadbeef ' + json.dumps({'cases': []}))\n"
        "    print('@@SG@@' + json.dumps({'status': 'ok', 'value': [0, 1]}))\n"
        "    sys.stderr.write('x')\n"
        "    return [9, 9]\n"
    )
    report = await _run(code)
    assert not report.ok and report.passed == 0


async def test_the_payload_with_expected_values_is_gone_before_learner_code_runs() -> None:
    code = (
        "def two_sum(nums, target):\n"
        "    return open('payload.json').read()\n"  # would leak every expected value
    )
    report = await _run(code)
    assert report.status == "error"
    assert "FileNotFoundError" in (report.first_failure.detail or "")


async def test_non_serializable_return_is_an_error() -> None:
    report = await _run("def two_sum(nums, target):\n    return {1, 2}\n")
    assert report.status == "error"
    assert "JSON" in (report.first_failure.detail or "")


async def test_visible_only_runs_just_the_examples() -> None:
    report = await _run(PY_GOOD, visible_only=True)
    assert report.ok and report.total == len(TWO_SUM.examples)


async def test_unsupported_language_raises_value_error() -> None:
    sandbox, _ = local_sandbox()
    with pytest.raises(ValueError):
        await run_problem_tests(sandbox, TWO_SUM, "cpp", "int main(){}")


@pytest.mark.skipif(not node_available(), reason="node is not installed")
async def test_javascript_solutions_run_too() -> None:
    assert (await _run(JS_GOOD, "javascript")).ok
    wrong = await _run("function twoSum(a, b) { return [0, 0]; }", "javascript")
    assert wrong.first_failure is not None and wrong.first_failure.label == "example 1"
    nothing = await _run("function twoSum(a, b) {}", "javascript")
    assert not nothing.ok
    throws = await _run("function twoSum(a, b) { throw new RangeError('boom'); }", "javascript")
    assert throws.status == "error" and "RangeError: boom" in (throws.first_failure.detail or "")


@pytest.mark.skipif(not node_available(), reason="node is not installed")
async def test_javascript_loop_times_out() -> None:
    report = await _run("function twoSum(a, b) { while (true) {} }", "javascript", limit=0.4)
    assert report.status == "timeout"


TS_GOOD = """
function twoSum(nums: number[], target: number): number[] {
  const seen = new Map<number, number>();
  for (let i = 0; i < nums.length; i++) {
    const need: number = target - nums[i];
    if (seen.has(need)) return [seen.get(need) as number, i];
    seen.set(nums[i], i);
  }
  return [];
}
"""


@pytest.mark.skipif(not node_available(), reason="node is not installed")
async def test_typescript_solutions_run_with_types_stripped() -> None:
    assert (await _run(TS_GOOD, "typescript")).ok
    wrong = await _run(
        "function twoSum(a: number[], b: number): number[] { return [0, 0]; }", "typescript"
    )
    assert wrong.first_failure is not None and wrong.first_failure.label == "example 1"
    throws = await _run(
        "function twoSum(a: number[], b: number): number[] { throw new RangeError('boom'); }",
        "typescript",
    )
    assert throws.status == "error" and "RangeError: boom" in (throws.first_failure.detail or "")


@pytest.mark.skipif(not node_available(), reason="node is not installed")
async def test_typescript_syntax_error_is_reported_not_crashing() -> None:
    report = await _run("function twoSum(a: number[ { return 1 }", "typescript")
    assert report.status == "error"


@pytest.mark.skipif(not node_available(), reason="node is not installed")
async def test_typescript_loop_times_out() -> None:
    report = await _run(
        "function twoSum(a: any, b: any): any { while (true) {} }", "typescript", limit=0.4
    )
    assert report.status == "timeout"
