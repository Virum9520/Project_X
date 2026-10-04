"""Arjuna's server tools: `run_tests` and `give_hint` (contracts in `agents/tools/*.yaml`).

Both authenticate with the signed tool token (`X-SG-Tool-Token`) and check `conversation_id`.
The learner and session come from the token, never the body.

`run_tests` runs the hidden tests against the learner's latest saved code snapshot in the E2B
sandbox. The reply is for the agent to speak: counts, a summary, and the first failure. Hidden
inputs and expected values are never returned; a failing hidden case comes back as a label such
as "empty input" (a public example also includes its input, expected value and the learner's
output). The result is stored as `code_run` evidence; it is `assisted` if Arjuna gave any hint on
the problem. The reply never says what the result means for the garden.

`give_hint` returns the next hint for the problem from the bank (the agent cannot skip levels)
and records it, so everything the learner solves afterwards on that problem is assisted.
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sg_api.arjuna.problems import MAX_HINT_LEVEL, SUPPORTED_LANGUAGES, Problem, get_problem
from sg_api.arjuna.runner import run_problem_tests, unavailable_report
from sg_api.arjuna.store import ArjunaStore, SessionCtx, get_arjuna_store
from sg_api.sessions.tool_tokens import ToolTokenClaims, check_conversation, require_tool_token
from sg_core.economics.usage import UsageContext
from sg_core.logging import get_logger
from sg_core.models.enums import CostCenter
from sg_core.providers.base import ProviderNotConfiguredError
from sg_core.providers.sandbox import SandboxClient, sandbox_client_from_settings

router = APIRouter(prefix="/v1/agent-tools", tags=["agent-tools"])
log = get_logger(__name__)

ARJUNA_CHARACTERS = ("arjuna", "panel")
MAX_AGENT_RUNS = 30
MAX_EXAMPLE_RUNS = 80
PROBLEM_ID = r"^p_[a-z0-9_]{1,60}$"


def get_sandbox() -> SandboxClient | None:
    """None when E2B is not configured; routes then report the sandbox as unavailable."""
    try:
        return sandbox_client_from_settings()
    except ProviderNotConfiguredError:
        return None


class FirstFailure(BaseModel):
    label: str
    kind: Literal["wrong_answer", "error", "timeout"]
    shareable: bool
    input: dict[str, Any] | None = None
    expected: Any = None
    actual: str | None = None
    detail: str | None = None


class RunTestsRequest(BaseModel):
    conversation_id: str
    problem_id: str = Field(pattern=PROBLEM_ID)


class RunTestsResponse(BaseModel):
    status: Literal[
        "passed",
        "failed",
        "error",
        "timeout",
        "no_code",
        "unsupported_language",
        "run_limit",
        "unavailable",
    ]
    passed: int = 0
    total: int = 0
    summary: str
    first_failure: FirstFailure | None = None
    assisted: bool = False
    run_id: str | None = None
    note: str = (
        "Say the result in plain words. Do not read hidden test inputs unless shareable is true. "
        "Do not say anything about the candidate's progress, score or garden."
    )


class GiveHintRequest(BaseModel):
    conversation_id: str
    problem_id: str = Field(pattern=PROBLEM_ID)


class GiveHintResponse(BaseModel):
    status: Literal["given", "exhausted"]
    level: int = 0
    hint: str = ""
    hints_remaining: int = 0
    note: str


def _require_arjuna(claims: ToolTokenClaims) -> None:
    if claims.character not in ARJUNA_CHARACTERS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this character does not run code")


def _problem(problem_id: str) -> Problem:
    problem = get_problem(problem_id)
    if problem is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"unknown problem {problem_id}: use an ID from fetch_question",
        )
    return problem


async def _ctx(store: ArjunaStore, claims: ToolTokenClaims) -> SessionCtx:
    ctx = await store.resolve(claims.user_id, claims.session_id)
    if ctx is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "this session was not recorded, so code cannot be run; continue verbally",
        )
    return ctx


@router.post("/run_tests", response_model=RunTestsResponse)
async def run_tests(
    body: RunTestsRequest,
    claims: Annotated[ToolTokenClaims, Depends(require_tool_token)],
    store: Annotated[ArjunaStore, Depends(get_arjuna_store)],
    sandbox: Annotated[SandboxClient | None, Depends(get_sandbox)],
) -> RunTestsResponse:
    check_conversation(claims, body.conversation_id)
    _require_arjuna(claims)
    problem = _problem(body.problem_id)
    ctx = await _ctx(store, claims)

    snapshot = await store.latest_snapshot(ctx, problem.id)
    if snapshot is None or not snapshot.code.strip():
        return RunTestsResponse(
            status="no_code",
            summary="There is no code in the editor for this problem yet.",
            note="Ask the candidate to write something first, then run the tests.",
        )
    if snapshot.language not in SUPPORTED_LANGUAGES:
        return RunTestsResponse(
            status="unsupported_language",
            summary=(
                f"Tests only run for {', '.join(SUPPORTED_LANGUAGES)}, not {snapshot.language}."
            ),
            note="Ask the candidate to switch the editor to Python or JavaScript, or review the "
            "code aloud instead.",
        )
    if await store.count_runs(ctx, "tests") >= MAX_AGENT_RUNS:
        return RunTestsResponse(
            status="run_limit", summary="The limit on test runs for this session was reached."
        )
    if sandbox is None:
        return RunTestsResponse(
            status="unavailable",
            summary="The code sandbox is not available right now.",
            note="Tell the candidate plainly, and carry on by tracing the code together aloud. "
            "Do not guess whether tests would pass.",
        )

    now = datetime.now(UTC)
    usage = UsageContext(
        cost_center=CostCenter.LEARNER,
        component="arjuna.run_tests",
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        idempotency_key=None,
    )
    try:
        report = await run_problem_tests(
            sandbox, problem, snapshot.language, snapshot.code, usage=usage
        )
    except Exception:
        log.warning("arjuna.run_tests.sandbox_failed", problem_id=problem.id, exc_info=True)
        report = unavailable_report("The code sandbox failed to start.")
    if report.status == "unavailable":
        return RunTestsResponse(
            status="unavailable",
            summary=report.summary,
            note="Tell the candidate plainly, and carry on by tracing the code together aloud. "
            "Do not guess whether tests would pass.",
        )

    assisted = bool(await store.hint_levels(ctx, problem.id))
    record = await store.record_run(
        ctx,
        problem=problem,
        snapshot=snapshot,
        report=report,
        kind="tests",
        assisted=assisted,
        now=now,
    )
    first = report.first_failure
    return RunTestsResponse(
        status=report.status,
        passed=report.passed,
        total=report.total,
        summary=report.summary,
        first_failure=(
            FirstFailure(
                label=first.label,
                kind=first.kind,
                shareable=first.shareable,
                input=first.input,
                expected=first.expected,
                actual=first.actual,
                detail=first.detail,
            )
            if first
            else None
        ),
        assisted=assisted,
        run_id=str(record.id),
    )


@router.post("/give_hint", response_model=GiveHintResponse)
async def give_hint(
    body: GiveHintRequest,
    claims: Annotated[ToolTokenClaims, Depends(require_tool_token)],
    store: Annotated[ArjunaStore, Depends(get_arjuna_store)],
) -> GiveHintResponse:
    check_conversation(claims, body.conversation_id)
    _require_arjuna(claims)
    problem = _problem(body.problem_id)
    ctx = await _ctx(store, claims)
    given = await store.hint_levels(ctx, problem.id)
    level = len(given) + 1
    if level > MAX_HINT_LEVEL:
        return GiveHintResponse(
            status="exhausted",
            note="No more hints exist. Ask a guiding question instead of giving the answer, or "
            "suggest moving on.",
        )
    text = problem.hints[level - 1]
    await store.record_hint(ctx, problem, level=level, content=text)
    return GiveHintResponse(
        status="given",
        level=level,
        hint=text,
        hints_remaining=MAX_HINT_LEVEL - level,
        note="Give this hint in your own words, once. Everything the candidate solves on this "
        "problem from now on is assisted: record it with assistance hinted (level 1 or 2) or "
        "heavily_assisted (level 3). Never give code.",
    )
