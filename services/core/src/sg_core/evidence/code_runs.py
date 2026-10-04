"""Turn Arjuna's stored `code_run` evidence into verdicts, deterministically (no LLM).

A hidden-tests run is already attributable evidence: C16 stores the quote, the exact code
snapshot, the sandbox run and the hints on that problem. This module only reads it back, so the
post-call pipeline can treat it like any other verdict and let the rules engine alone decide
growth.

Rules, all deterministic:
- Outcome: every test passed -> demonstrated; some passed -> partial; none passed -> not
  demonstrated; a timeout or sandbox error -> unassessable (never growth, never a miss).
- Assistance is what was recorded at run time. It is carried forward or raised (any hint on the
  run), never lowered, so assisted and independent evidence stay separate.
- One assessment per concept (assessments are keyed by session, concept and dimension): the run
  that carries credit and was independent wins, then the better outcome, then the latest. It
  cites its own evidence row only, so a hinted run never lends credit to an unhinted one.
- The dimension is always `application`.
"""

from collections.abc import Iterable, Mapping

from sg_core.evidence.types import CodeRun, ConceptInfo, Verdict
from sg_core.models.enums import AssessmentOutcome, Assistance, Dimension

CODE_RUN_JUDGE = "rules:code_run@1"
CODE_RUN_UNCERTAINTY = 0.05
_RANK = {
    AssessmentOutcome.DEMONSTRATED: 3,
    AssessmentOutcome.PARTIAL: 2,
    AssessmentOutcome.NOT_DEMONSTRATED: 1,
    AssessmentOutcome.UNASSESSABLE: 0,
}


def outcome_of(run: CodeRun) -> AssessmentOutcome:
    if run.status in ("timeout", "error") or run.total <= 0:
        return AssessmentOutcome.UNASSESSABLE
    if run.passed >= run.total:
        return AssessmentOutcome.DEMONSTRATED
    if run.passed > 0:
        return AssessmentOutcome.PARTIAL
    return AssessmentOutcome.NOT_DEMONSTRATED


def assistance_of(run: CodeRun) -> Assistance:
    if run.assistance is Assistance.ASSISTED or run.hint_count > 0:
        return Assistance.ASSISTED
    return Assistance.INDEPENDENT


def _priority(run: CodeRun) -> tuple[bool, bool, int, float]:
    outcome = outcome_of(run)
    credit = outcome in (AssessmentOutcome.DEMONSTRATED, AssessmentOutcome.PARTIAL)
    return (
        credit,
        assistance_of(run) is Assistance.INDEPENDENT,
        _RANK[outcome],
        run.occurred_at.timestamp(),
    )


def code_run_verdicts(runs: Iterable[CodeRun], catalog: Mapping[str, ConceptInfo]) -> list[Verdict]:
    """One verdict per concept that has code evidence."""
    best: dict[str, CodeRun] = {}
    for run in runs:
        if run.concept_key not in catalog:
            continue
        current = best.get(run.concept_key)
        if current is None or _priority(run) > _priority(current):
            best[run.concept_key] = run
    verdicts: list[Verdict] = []
    for key in sorted(best):
        run = best[key]
        assistance = assistance_of(run)
        how = "after a hint" if assistance is Assistance.ASSISTED else "with no hints"
        verdicts.append(
            Verdict(
                concept_key=key,
                dimension=Dimension.APPLICATION.value,
                outcome=outcome_of(run),
                assistance=assistance,
                citations=(),
                rationale=(
                    f"Hidden tests: {run.passed} of {run.total} passed ({run.status}), {how}."
                ),
                uncertainty=CODE_RUN_UNCERTAINTY,
                problem_family=run.problem_family,
                flags=("code_run",),
                code_run=run,
            )
        )
    return verdicts


def code_digest(runs: Iterable[CodeRun]) -> str:
    """Stable fingerprint of the code evidence a pass looked at (for idempotency)."""
    return ",".join(sorted(r.dedupe_key for r in runs))
