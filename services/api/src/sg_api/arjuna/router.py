"""Learner-facing routes for the Arjuna technical interview.

- `GET  /v1/arjuna/plan`: what Arjuna will cover, derived from the learner's résumé and job
  description (deterministic keyword parse; nothing in the documents is treated as instructions).
- `POST /v1/arjuna/sessions`: starts the voice session (via `POST /v1/sessions` logic) and adds
  the plan to the conversation's dynamic variables and to the session's attributes.
- `GET  /v1/arjuna/problems/{id}`: the public problem view for the editor (statement, starter
  code, example cases). Hidden tests never leave the server.
- `PUT  /v1/arjuna/sessions/{id}/code`: autosave a code snapshot (the exact code later cited by
  test evidence).
- `POST /v1/arjuna/sessions/{id}/run-examples`: practice run of the public examples only; never
  evidence.
- `GET  /v1/arjuna/sessions/{id}/runs`: the agent's test runs, for the editor's results panel.
- `POST /v1/arjuna/scribe-token`: single-use token for realtime Scribe live captions.
"""

import dataclasses
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from sg_api.arjuna.plan import InterviewPlan, build_plan, render_for_agent
from sg_api.arjuna.problems import (
    SUPPORTED_LANGUAGES,
    Problem,
    get_problem,
    public_examples,
    starter_code,
)
from sg_api.arjuna.runner import run_problem_tests
from sg_api.arjuna.store import (
    MAX_SNAPSHOT_CHARS,
    ArjunaStore,
    PlanSources,
    SessionCtx,
    get_arjuna_store,
)
from sg_api.arjuna.tools import MAX_EXAMPLE_RUNS, PROBLEM_ID, get_sandbox
from sg_api.drona.store import SessionStore, get_session_store
from sg_api.sessions.briefing import BriefingProvider, get_briefing_provider
from sg_api.sessions.identity import Learner, current_learner
from sg_api.sessions.router import (
    SessionStartRequest,
    SessionStartResponse,
    get_elevenlabs,
    start_session,
)
from sg_core.economics.usage import UsageContext
from sg_core.logging import get_logger
from sg_core.models.enums import CostCenter
from sg_core.providers.elevenlabs import ElevenLabsClient, ElevenLabsError
from sg_core.providers.sandbox import SandboxClient
from sg_core.settings import Environment, Settings, get_settings

router = APIRouter(prefix="/v1/arjuna", tags=["arjuna"])
log = get_logger(__name__)

EDITOR_LANGUAGES = Literal["python", "javascript", "typescript", "java", "cpp", "go"]
RunnableLanguage = Literal["python", "javascript"]
MAX_PLAN_VARIABLE_CHARS = 1800


class ConceptMention(BaseModel):
    concept_id: str
    mentions: int


class PlanProblem(BaseModel):
    id: str
    title: str
    concept_id: str
    difficulty: int


class PlanOut(BaseModel):
    role: str
    grounded: bool
    has_resume: bool
    has_job_description: bool
    probes: list[str]
    # Self-reported on the résumé: used to choose questions, never as evidence.
    resume_claims: list[ConceptMention]
    job_requirements: list[ConceptMention]
    projects: list[str]
    problems: list[PlanProblem]


def plan_out(plan: InterviewPlan) -> PlanOut:
    problems: list[PlanProblem] = []
    for pid in plan.problems:
        p = get_problem(pid)
        if p is not None:
            problems.append(
                PlanProblem(
                    id=p.id, title=p.title, concept_id=p.concept_key, difficulty=p.difficulty
                )
            )
    return PlanOut(
        role=plan.role,
        grounded=plan.grounded,
        has_resume=plan.has_resume,
        has_job_description=plan.has_job_description,
        probes=list(plan.probes),
        resume_claims=[
            ConceptMention(concept_id=m.concept_key, mentions=m.count) for m in plan.claims
        ],
        job_requirements=[
            ConceptMention(concept_id=m.concept_key, mentions=m.count) for m in plan.requirements
        ],
        projects=list(plan.projects),
        problems=problems,
    )


async def _sources(store: ArjunaStore, settings: Settings, user_id: str) -> PlanSources:
    try:
        return await store.plan_sources(user_id)
    except Exception:
        log.warning("arjuna.plan_sources_failed", exc_info=True)
        if settings.environment not in (Environment.LOCAL, Environment.TEST):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "could not read your documents"
            ) from None
        return PlanSources(None, None, frozenset())


async def _plan(
    store: ArjunaStore, settings: Settings, learner: Learner, role: str = "Software Engineer"
) -> InterviewPlan:
    sources = await _sources(store, settings, learner.user_id)
    return build_plan(
        resume_text=sources.resume_text,
        job_description_text=sources.job_description_text,
        role=role,
        concept_keys=sources.concept_keys,
    )


@router.get("/plan", response_model=PlanOut)
async def get_plan(
    learner: Annotated[Learner, Depends(current_learner)],
    settings: Annotated[Settings, Depends(get_settings)],
    store: Annotated[ArjunaStore, Depends(get_arjuna_store)],
) -> PlanOut:
    return plan_out(await _plan(store, settings, learner))


class ArjunaSessionRequest(BaseModel):
    language: RunnableLanguage = "python"
    focus_concept_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")


class ArjunaSessionResponse(SessionStartResponse):
    plan: PlanOut
    language: RunnableLanguage


@router.post("/sessions", response_model=ArjunaSessionResponse, status_code=status.HTTP_201_CREATED)
async def start_interview(
    body: ArjunaSessionRequest,
    learner: Annotated[Learner, Depends(current_learner)],
    settings: Annotated[Settings, Depends(get_settings)],
    briefings: Annotated[BriefingProvider, Depends(get_briefing_provider)],
    elevenlabs: Annotated[ElevenLabsClient, Depends(get_elevenlabs)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
    store: Annotated[ArjunaStore, Depends(get_arjuna_store)],
) -> ArjunaSessionResponse:
    plan = await _plan(store, settings, learner)
    focus = body.focus_concept_id or (plan.probes[0] if plan.probes else None)
    started = await start_session(
        SessionStartRequest(character="arjuna", focus_concept_id=focus),
        learner,
        settings,
        briefings,
        elevenlabs,
        sessions,
    )
    role = started.dynamic_variables.get("target_role") or plan.role
    plan = dataclasses.replace(plan, role=role)
    rendered = render_for_agent(plan)[:MAX_PLAN_VARIABLE_CHARS]
    started.dynamic_variables["interview_plan"] = rendered
    started.dynamic_variables["preferred_language"] = body.language
    if started.persisted:
        try:
            ctx = await store.resolve(learner.user_id, started.session_id)
            if ctx is not None:
                await store.set_attributes(
                    ctx,
                    {
                        "language": body.language,
                        "interview_plan": plan_out(plan).model_dump(),
                    },
                )
        except Exception:
            log.warning("arjuna.plan_persist_failed", session_id=started.session_id, exc_info=True)
    return ArjunaSessionResponse(
        **started.model_dump(), plan=plan_out(plan), language=body.language
    )


# ── The editor ────────────────────────────────────────────────────────────────────────────────


class ExampleOut(BaseModel):
    label: str
    input: dict[str, Any]
    expected: Any


class ProblemOut(BaseModel):
    id: str
    title: str
    statement: str
    difficulty: int
    concept_id: str
    function: str
    params: list[str]
    language: str
    starter_code: str
    examples: list[ExampleOut]
    tests_available: bool
    runnable_languages: list[str]


def problem_out(problem: Problem, language: str) -> ProblemOut:
    runnable = language in SUPPORTED_LANGUAGES
    return ProblemOut(
        id=problem.id,
        title=problem.title,
        statement=problem.statement,
        difficulty=problem.difficulty,
        concept_id=problem.concept_key,
        function=problem.js_function if language == "javascript" else problem.function,
        params=list(problem.params),
        language=language,
        # Languages without a harness still get an editable stub with the signature in a comment.
        starter_code=starter_code(problem, language if runnable else "python")
        if runnable
        else (
            f"// {problem.title}\n"
            f"// Tests do not run for {language}; talk it through with Arjuna.\n"
        ),
        examples=[ExampleOut(**e) for e in public_examples(problem)],
        tests_available=runnable,
        runnable_languages=list(SUPPORTED_LANGUAGES),
    )


@router.get("/problems/{problem_id}", response_model=ProblemOut)
async def get_problem_view(
    problem_id: str,
    _learner: Annotated[Learner, Depends(current_learner)],
    language: EDITOR_LANGUAGES = "python",
) -> ProblemOut:
    problem = get_problem(problem_id)
    if problem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown problem")
    return problem_out(problem, language)


async def _session(store: ArjunaStore, learner: Learner, session_id: str) -> SessionCtx:
    ctx = await store.resolve(learner.user_id, session_id)
    if ctx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return ctx


class CodeIn(BaseModel):
    problem_id: str = Field(pattern=PROBLEM_ID)
    language: EDITOR_LANGUAGES
    code: str = Field(max_length=MAX_SNAPSHOT_CHARS)
    trigger: Literal["autosave", "run", "submit"] = "autosave"


class SnapshotOut(BaseModel):
    snapshot_id: str
    duplicate: bool


@router.put("/sessions/{session_id}/code", response_model=SnapshotOut)
async def save_code(
    session_id: str,
    body: CodeIn,
    learner: Annotated[Learner, Depends(current_learner)],
    store: Annotated[ArjunaStore, Depends(get_arjuna_store)],
) -> SnapshotOut:
    if get_problem(body.problem_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown problem")
    ctx = await _session(store, learner, session_id)
    ref = await store.save_snapshot(
        ctx,
        problem_id=body.problem_id,
        language=body.language,
        code=body.code,
        trigger=body.trigger,
    )
    return SnapshotOut(snapshot_id=str(ref.id), duplicate=ref.duplicate)


class RunExamplesIn(BaseModel):
    problem_id: str = Field(pattern=PROBLEM_ID)
    language: RunnableLanguage
    code: str = Field(min_length=1, max_length=MAX_SNAPSHOT_CHARS)


class ExampleResult(BaseModel):
    label: str
    passed: bool
    input: dict[str, Any]
    expected: Any
    actual: str | None = None
    detail: str | None = None


class RunExamplesOut(BaseModel):
    status: str
    passed: int
    total: int
    summary: str
    results: list[ExampleResult]


@router.post("/sessions/{session_id}/run-examples", response_model=RunExamplesOut)
async def run_examples(
    session_id: str,
    body: RunExamplesIn,
    learner: Annotated[Learner, Depends(current_learner)],
    store: Annotated[ArjunaStore, Depends(get_arjuna_store)],
    sandbox: Annotated[SandboxClient | None, Depends(get_sandbox)],
) -> RunExamplesOut:
    problem = get_problem(body.problem_id)
    if problem is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown problem")
    ctx = await _session(store, learner, session_id)
    if await store.count_runs(ctx, "examples") >= MAX_EXAMPLE_RUNS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many practice runs")
    if sandbox is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the code sandbox is unavailable")
    await store.save_snapshot(
        ctx, problem_id=problem.id, language=body.language, code=body.code, trigger="run"
    )
    snapshot = await store.latest_snapshot(ctx, problem.id)
    usage = UsageContext(
        cost_center=CostCenter.LEARNER,
        component="arjuna.run_examples",
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        idempotency_key=None,
    )
    try:
        report = await run_problem_tests(
            sandbox, problem, body.language, body.code, visible_only=True, usage=usage
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except Exception as exc:
        log.warning("arjuna.run_examples.sandbox_failed", exc_info=True)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "the code sandbox is unavailable"
        ) from exc
    if snapshot is not None:
        await store.record_run(
            ctx,
            problem=problem,
            snapshot=snapshot,
            report=report,
            kind="examples",
            assisted=False,
            now=datetime.now(UTC),
        )
    failed = {f.label: f for f in report.failures}
    # With no per-case information (the run itself failed) nothing counts as passed.
    known = bool(report.failures) or report.status == "passed"
    results = []
    for example in public_examples(problem):
        f = failed.get(example["label"])
        results.append(
            ExampleResult(
                label=example["label"],
                passed=f is None and known,
                input=example["input"],
                expected=example["expected"],
                actual=f.actual if f else None,
                detail=(f.detail or ("timed out" if f.kind == "timeout" else None)) if f else None,
            )
        )
    return RunExamplesOut(
        status=report.status,
        passed=report.passed,
        total=report.total,
        summary=report.summary,
        results=results,
    )


class RunOut(BaseModel):
    id: str
    problem_id: str
    status: str
    passed: int
    total: int
    summary: str
    first_failure: str | None
    assisted: bool
    at: datetime


@router.get("/sessions/{session_id}/runs", response_model=list[RunOut])
async def list_runs(
    session_id: str,
    learner: Annotated[Learner, Depends(current_learner)],
    store: Annotated[ArjunaStore, Depends(get_arjuna_store)],
    after: Annotated[datetime | None, Query()] = None,
) -> list[RunOut]:
    ctx = await _session(store, learner, session_id)
    runs = await store.list_runs(ctx, after=after, kind="tests")
    return [
        RunOut(
            id=str(r.id),
            problem_id=r.problem_id,
            status=r.status,
            passed=r.passed,
            total=r.total,
            summary=r.summary,
            first_failure=r.first_failure,
            assisted=r.assisted,
            at=r.at,
        )
        for r in runs
    ]


class ScribeTokenOut(BaseModel):
    token: str
    model_id: str = "scribe_v2_realtime"


@router.post("/scribe-token", response_model=ScribeTokenOut)
async def scribe_token(
    _learner: Annotated[Learner, Depends(current_learner)],
    elevenlabs: Annotated[ElevenLabsClient, Depends(get_elevenlabs)],
) -> ScribeTokenOut:
    try:
        return ScribeTokenOut(token=await elevenlabs.create_scribe_token())
    except ElevenLabsError as exc:
        log.warning("arjuna.scribe_token_failed", status=exc.status_code)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "live captions are unavailable") from exc
