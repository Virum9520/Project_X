"""Run a problem's tests in the E2B sandbox and turn the output into a report Arjuna can speak.

Nothing here executes learner code in our own process. Hidden inputs and expected values never
leave this module: only the label of a failing hidden case does, unless the case is shareable
(a public example), in which case its input, expected value and the learner's output are
included so the learner can debug it.
"""

from dataclasses import dataclass, field
from typing import Any

from sg_api.arjuna.harness import build_run, parse_output, total_timeout_s
from sg_api.arjuna.problems import Problem
from sg_core.economics.usage import UsageContext
from sg_core.providers.sandbox import SandboxClient

MAX_FAILURES = 3


@dataclass(frozen=True)
class Failure:
    index: int
    label: str
    kind: str  # wrong_answer | error | timeout
    shareable: bool
    input: dict[str, Any] | None = None
    expected: Any = None
    actual: str | None = None
    detail: str | None = None

    def sentence(self) -> str:
        where = f"the {self.label} case" if not self.shareable else f"{self.label}"
        if self.kind == "timeout":
            return f"{where} ran out of time"
        if self.kind == "error":
            return f"{where} crashed: {self.detail or 'runtime error'}"
        return f"{where} returned a wrong answer"


@dataclass(frozen=True)
class TestReport:
    __test__ = False  # not a pytest class

    status: str  # passed | failed | error | timeout | unavailable
    passed: int
    total: int
    duration_ms: int
    summary: str
    failures: tuple[Failure, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "passed"

    @property
    def first_failure(self) -> Failure | None:
        return self.failures[0] if self.failures else None


def unavailable_report(reason: str) -> TestReport:
    return TestReport("unavailable", 0, 0, 0, reason)


async def run_problem_tests(
    sandbox: SandboxClient,
    problem: Problem,
    language: str,
    code: str,
    *,
    visible_only: bool = False,
    usage: UsageContext | None = None,
) -> TestReport:
    """Run the cases and report. Raises `ValueError` for an unsupported language or oversized
    code; sandbox/provider failures propagate to the caller (which reports "unavailable")."""
    run = build_run(problem, language, code, visible_only=visible_only)
    result = await sandbox.run(
        run.command,
        files=run.files,
        timeout_seconds=total_timeout_s(problem, len(run.cases)),
        allow_internet=False,
        usage=usage,
    )
    duration_ms = int(result.duration_seconds * 1000)
    total = len(run.cases)
    if result.timed_out:
        return TestReport(
            "timeout", 0, total, duration_ms, "The whole run timed out before finishing."
        )
    parsed = parse_output(result.stdout, run.nonce)
    if parsed is None:
        tail = [ln for ln in result.stderr.strip().splitlines() if ln.strip()]
        detail = tail[-1][:240] if tail else "the test runner produced no result"
        return TestReport("error", 0, total, duration_ms, f"The code could not be run: {detail}")

    by_index = {c.index: c for c in run.cases}
    failures: list[Failure] = []
    passed = 0
    any_timeout = False
    for r in sorted(parsed, key=lambda x: x.index):
        case = by_index.get(r.index)
        if case is None:
            continue
        if r.status == "pass":
            passed += 1
            continue
        any_timeout = any_timeout or r.status == "timeout"
        kind = {"timeout": "timeout", "error": "error"}.get(r.status, "wrong_answer")
        shows_inputs = case.shareable
        failures.append(
            Failure(
                index=r.index,
                label=case.label,
                kind=kind,
                shareable=shows_inputs,
                input=(dict(zip(problem.params, case.args, strict=True)) if shows_inputs else None),
                expected=case.expected if shows_inputs else None,
                actual=r.actual or None if shows_inputs else None,
                detail=r.detail or None if kind == "error" else None,
            )
        )
    if passed == total:
        return TestReport("passed", passed, total, duration_ms, f"All {total} tests passed.")
    errors = sum(1 for f in failures if f.kind == "error")
    status = "error" if errors == len(failures) == total else "timeout" if any_timeout else "failed"
    first = failures[0]
    summary = f"Passed {passed} of {total} tests. First failure: {first.sentence()}."
    return TestReport(status, passed, total, duration_ms, summary, tuple(failures[:MAX_FAILURES]))


__all__ = ["Failure", "TestReport", "run_problem_tests", "unavailable_report"]
