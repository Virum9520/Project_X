"""`POST /v1/agent-tools/log_commitment` and `/report_commitment_progress` (Bhima's tools).

Contracts: `agents/tools/log_commitment.yaml`, `agents/tools/report_commitment_progress.yaml`.
The learner comes from the signed tool token, never the body; the body's `conversation_id` must
match the token. A report is a self-report, stored apart from anything the app observed, and
neither tool touches evidence or the garden.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sg_api.accountability.deps import (
    UserDirectory,
    UserRef,
    get_accountability_store,
    get_user_directory,
)
from sg_api.sessions.tool_tokens import ToolTokenClaims, check_conversation, require_tool_token
from sg_core.accountability import (
    AccountabilityStore,
    CommitmentRejected,
    log_commitment,
    report_progress,
)

router = APIRouter(prefix="/v1/agent-tools", tags=["agent-tools"])

_CONCEPT_ID = r"^[a-z0-9_]+(\.[a-z0-9_]+)+$"


class LogCommitmentRequest(BaseModel):
    conversation_id: str
    description: str = Field(min_length=1, max_length=1000)
    due_local: str = Field(max_length=40)
    concept_id: str | None = Field(default=None, pattern=_CONCEPT_ID, max_length=128)
    confirmed_by_learner: bool


class LogCommitmentResponse(BaseModel):
    commitment_id: str
    status: Literal["saved", "already_saved"]
    due_at: str
    message: str


class ReportProgressRequest(BaseModel):
    conversation_id: str
    commitment_id: str
    status: Literal["done", "partly_done", "not_done", "wants_to_change"]
    learner_words: str | None = Field(default=None, max_length=600)


class ReportProgressResponse(BaseModel):
    commitment_id: str
    recorded: Literal["self_reported"] = "self_reported"
    commitment_status: str
    message: str


async def _learner(claims: ToolTokenClaims, users: UserDirectory) -> UserRef:
    user = await users.resolve(claims.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "learner profile not found")
    return user


@router.post("/log_commitment", response_model=LogCommitmentResponse)
async def log_commitment_tool(
    body: LogCommitmentRequest,
    claims: Annotated[ToolTokenClaims, Depends(require_tool_token)],
    store: Annotated[AccountabilityStore, Depends(get_accountability_store)],
    users: Annotated[UserDirectory, Depends(get_user_directory)],
) -> LogCommitmentResponse:
    check_conversation(claims, body.conversation_id)
    user = await _learner(claims, users)
    try:
        row, created = await log_commitment(
            store,
            user_id=user.id,
            tz=user.timezone,
            description=body.description,
            due_local=body.due_local,
            confirmed_by_learner=body.confirmed_by_learner,
            concept_key=body.concept_id,
        )
    except CommitmentRejected as exc:
        # The agent reads this message aloud-adjacent: keep it plain and actionable.
        raise HTTPException(422, f"{exc.code}: {exc}") from exc
    assert row.due_at is not None
    return LogCommitmentResponse(
        commitment_id=str(row.id),
        status="saved" if created else "already_saved",
        due_at=row.due_at.isoformat(),
        message="Commitment saved. It is the learner's own promise, not verified progress.",
    )


@router.post("/report_commitment_progress", response_model=ReportProgressResponse)
async def report_commitment_progress_tool(
    body: ReportProgressRequest,
    claims: Annotated[ToolTokenClaims, Depends(require_tool_token)],
    store: Annotated[AccountabilityStore, Depends(get_accountability_store)],
    users: Annotated[UserDirectory, Depends(get_user_directory)],
) -> ReportProgressResponse:
    check_conversation(claims, body.conversation_id)
    user = await _learner(claims, users)
    try:
        commitment_id = uuid.UUID(body.commitment_id)
    except ValueError as exc:
        raise HTTPException(422, "bad commitment_id") from exc
    row = await report_progress(
        store,
        user_id=user.id,
        commitment_id=commitment_id,
        status=body.status,
        learner_words=body.learner_words,
    )
    if row is None:  # unknown, or someone else's: indistinguishable on purpose
        raise HTTPException(status.HTTP_404_NOT_FOUND, "commitment not found")
    return ReportProgressResponse(
        commitment_id=str(row.id),
        commitment_status=row.status.value,
        message="Noted as the learner's own report.",
    )
