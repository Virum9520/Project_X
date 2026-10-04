"""`POST /v1/agent-tools/fetch_question`: the next question for the live conversation.

Contract: `agents/tools/fetch_question.yaml`. The learner and session come from the signed tool
token; the body's `conversation_id` must match it. Questions are derived from the concept's
rubric (see `sg_api.drona.questions`), so every answer links to a known concept and criterion.
The returned prompt is plain text for the learner's screen; `hints` are for the agent only.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sg_api.arjuna.problems import get_problem, select_problem
from sg_api.drona.questions import SERVED_KINDS, parse_exclusions, select_question
from sg_api.drona.store import SessionStore, get_session_store
from sg_api.sessions.tool_tokens import ToolTokenClaims, check_conversation, require_tool_token
from sg_core.logging import get_logger

router = APIRouter(prefix="/v1/agent-tools", tags=["agent-tools"])
log = get_logger(__name__)

CONCEPT_KEY = r"^[a-z0-9_]+(\.[a-z0-9_]+)+$"


class FetchQuestionRequest(BaseModel):
    conversation_id: str
    kind: Literal["concept_check", "cross_question", "teach_back", "coding_problem", "behavioral"]
    concept_id: str | None = Field(default=None, pattern=CONCEPT_KEY, max_length=128)
    difficulty: Literal["easier", "same", "harder"] = "same"
    exclude_question_ids: str | None = Field(default=None, max_length=2000)


class FetchQuestionResponse(BaseModel):
    question_id: str
    kind: str
    concept_id: str
    title: str
    prompt: str
    hints: list[str]
    note: str


async def _coding_problem(
    body: FetchQuestionRequest, claims: ToolTokenClaims, store: SessionStore
) -> FetchQuestionResponse:
    """Arjuna's coding problems come from the problem bank (`sg_api.arjuna.problems`)."""
    if claims.character not in ("arjuna", "panel"):
        raise HTTPException(422, "coding problems are given by Arjuna; ask a concept question")
    excluded = parse_exclusions(body.exclude_question_ids)
    seen_families = {p.family for pid in excluded if (p := get_problem(pid)) is not None}
    concept_key = body.concept_id
    if concept_key is None:
        try:
            concept_key = await store.session_focus(claims.user_id, claims.session_id)
        except Exception:
            log.warning("fetch_question.focus_failed", exc_info=True)
    problem, matched = select_problem(
        concept_key, difficulty=body.difficulty, exclude=excluded, exclude_families=seen_families
    )
    note = (
        "Present it aloud briefly, call show_question_card with this question_id, then "
        "open_editor with this problem_id. Get hints only with give_hint, never from memory."
    )
    if concept_key and not matched:
        note += f" There is no problem for {concept_key} yet; this is a fundamentals problem."
    if problem.id in excluded:
        note += " Every matching problem was already used; this one repeats."
    return FetchQuestionResponse(
        question_id=problem.id,
        kind="coding_problem",
        concept_id=problem.concept_key,
        title=problem.title,
        prompt=problem.statement,
        hints=[],
        note=note,
    )


@router.post("/fetch_question", response_model=FetchQuestionResponse)
async def fetch_question(
    body: FetchQuestionRequest,
    claims: Annotated[ToolTokenClaims, Depends(require_tool_token)],
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> FetchQuestionResponse:
    check_conversation(claims, body.conversation_id)
    if body.kind == "coding_problem":
        return await _coding_problem(body, claims, store)
    if body.kind not in SERVED_KINDS:
        raise HTTPException(422, f"unsupported question kind {body.kind}")
    try:
        concept_key = body.concept_id or await store.session_focus(
            claims.user_id, claims.session_id
        )
        if concept_key is None:
            raise HTTPException(
                422,
                "no concept to ask about: pass concept_id",
            )
        concept = await store.concept_rubric(concept_key)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("fetch_question.failed", exc_info=True)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "question bank unavailable"
        ) from exc
    if concept is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"unknown concept {concept_key}: use a curriculum concept ID"
        )
    question = select_question(
        concept,
        body.kind,
        difficulty=body.difficulty,
        exclude=parse_exclusions(body.exclude_question_ids),
    )
    note = (
        "Show it with show_question_card. Hints are for you only; never read them out as an answer."
        if body.kind != "teach_back"
        else "Teach-back: you are the confused student. Show the card, then only ask beginner "
        "questions. Voice one confusion from hints, but never explain or confirm."
    )
    if question.repeat:
        note += " Every variant was already used; this one repeats."
    return FetchQuestionResponse(
        question_id=question.question_id,
        kind=question.kind,
        concept_id=question.concept_id,
        title=question.title,
        prompt=question.prompt,
        hints=question.hints,
        note=note,
    )
