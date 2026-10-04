"""`/v1/garden/*`: the learner's garden, analytics, memory panel and Ask Sanjaya.

Auth is the signed-in learner (Clerk bearer; dev headers only in local/test, see
`sessions.identity`). Every route is scoped to that learner; nothing takes a user id.
"""

import uuid
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status

from sg_api.garden.analytics import METRICS, AnalyticsError, make_query
from sg_api.garden.schemas import (
    AnalyticsOut,
    AskIn,
    AskOut,
    CorrectMemoryIn,
    GardenDatasetOut,
    GardenSnapshotOut,
    MemoryImpactOut,
    MemoryOut,
    RevisionOut,
)
from sg_api.garden.service import GardenService, UnknownLearner, get_garden_service
from sg_api.sessions.identity import Learner, current_learner
from sg_core.memory import MemoryNotFound, MemoryRuleViolation

router = APIRouter(prefix="/v1/garden", tags=["garden"])

LearnerDep = Annotated[Learner, Depends(current_learner)]
ServiceDep = Annotated[GardenService, Depends(get_garden_service)]


def analytics_http_error(exc: AnalyticsError) -> NoReturn:
    code = status.HTTP_404_NOT_FOUND if exc.not_found else 422
    raise HTTPException(code, str(exc)) from exc


def memory_http_error(exc: Exception) -> NoReturn:
    if isinstance(exc, MemoryNotFound | UnknownLearner):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "memory not found") from exc
    if isinstance(exc, MemoryRuleViolation):
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    raise exc


@router.get("/snapshot", response_model=GardenSnapshotOut)
async def get_snapshot(
    learner: LearnerDep,
    service: ServiceDep,
    rev: Annotated[int | None, Query(ge=0, description="Garden revision (time travel)")] = None,
) -> GardenSnapshotOut:
    """The `GardenSnapshot` the 3D scene renders, now or at revision `rev`."""
    return await service.snapshot(learner.user_id, rev)


@router.get("/revisions", response_model=list[RevisionOut])
async def list_revisions(learner: LearnerDep, service: ServiceDep) -> list[RevisionOut]:
    return await service.revisions(learner.user_id)


@router.get("/dataset", response_model=GardenDatasetOut)
async def get_dataset(learner: LearnerDep, service: ServiceDep) -> GardenDatasetOut:
    """Everything the dashboard renders: plants, evidence, growth events, sessions, memories."""
    return await service.dataset(learner.user_id)


@router.get("/analytics", response_model=AnalyticsOut)
async def get_analytics(
    learner: LearnerDep,
    service: ServiceDep,
    metric: Annotated[str, Query(description=f"One of: {', '.join(METRICS)}")],
    domain: str | None = None,
    concept_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> AnalyticsOut:
    try:
        query = make_query(domain, concept_id, date_from, date_to)
        return await service.analytics(learner.user_id, metric, query)
    except AnalyticsError as exc:
        analytics_http_error(exc)


@router.get("/memories", response_model=list[MemoryOut])
async def list_memories(learner: LearnerDep, service: ServiceDep) -> list[MemoryOut]:
    """What the mentors remember about this learner, with why and which plants it shapes."""
    return await service.memories(learner.user_id)


@router.get("/memories/{memory_id}/impact", response_model=MemoryImpactOut)
async def memory_impact(
    memory_id: uuid.UUID, learner: LearnerDep, service: ServiceDep
) -> MemoryImpactOut:
    """Plants a correction would touch, shown before the learner commits it."""
    try:
        return await service.memory_impact(learner.user_id, memory_id)
    except (MemoryNotFound, UnknownLearner) as exc:
        memory_http_error(exc)


@router.post("/memories/{memory_id}/correct", response_model=MemoryOut)
async def correct_memory(
    memory_id: uuid.UUID, body: CorrectMemoryIn, learner: LearnerDep, service: ServiceDep
) -> MemoryOut:
    """Append a corrected revision; the old wording stays in history, marked superseded."""
    try:
        return await service.correct_memory(learner.user_id, memory_id, body.content)
    except (MemoryNotFound, MemoryRuleViolation, UnknownLearner) as exc:
        memory_http_error(exc)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: uuid.UUID, learner: LearnerDep, service: ServiceDep) -> None:
    """Delete one of the learner's own private reflections (every other layer is corrected)."""
    try:
        await service.delete_memory(learner.user_id, memory_id)
    except (MemoryNotFound, MemoryRuleViolation, UnknownLearner) as exc:
        memory_http_error(exc)


@router.post("/ask", response_model=AskOut)
async def ask(body: AskIn, learner: LearnerDep, service: ServiceDep) -> AskOut:
    """Ask Sanjaya about your own garden. Answers cite evidence ids."""
    return await service.ask(learner.user_id, body.question)
