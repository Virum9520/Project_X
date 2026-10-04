"""Optional delivery observations: `POST /v1/sessions/{id}/delivery`.

The browser may compute three numbers during an interview, only if the learner opted in:
framing (how much of the time their face was in frame), gaze toward the camera, and speaking pace
(words per minute from transcript timing). Frames never leave the browser: this route accepts
nothing but those aggregates (`extra="forbid"`, bounded numbers), and stores them as one
provisional memory. They are observations about delivery, never about honesty, personality or
competence, they never grow a plant, and the wording stored says so.
"""

import uuid
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from sg_api.drona.store import parse_uuid
from sg_api.sessions.identity import Learner, current_learner
from sg_core.db import get_sessionmaker
from sg_core.logging import get_logger
from sg_core.memory.store import MemoryStore, NewMemory
from sg_core.models import User
from sg_core.models.enums import Character, MemoryLayer, MemorySource, MemoryStatus
from sg_core.models.sessions import Session as SessionRow

router = APIRouter(prefix="/v1/sessions", tags=["vidura"])
log = get_logger(__name__)

DELIVERY_KIND = "delivery_observation"


class DeliverySummary(BaseModel):
    """Aggregates only. Anything else in the body is rejected."""

    model_config = ConfigDict(extra="forbid")

    consent: Literal[True]
    duration_s: float = Field(gt=0, le=7200)
    samples: int = Field(ge=1, le=200_000)
    framing_ratio: float = Field(ge=0, le=1)
    gaze_ratio: float = Field(ge=0, le=1)
    pace_wpm: float | None = Field(default=None, ge=0, le=400)


def describe(summary: DeliverySummary) -> str:
    minutes = max(1, round(summary.duration_s / 60))
    parts = [
        f"face in frame {round(summary.framing_ratio * 100)}% of samples",
        f"looking toward the camera {round(summary.gaze_ratio * 100)}% of samples",
    ]
    if summary.pace_wpm is not None:
        parts.append(f"speaking pace about {round(summary.pace_wpm)} words per minute")
    return (
        f"Delivery in a {minutes} minute interview (opt-in, measured in the browser): "
        + ", ".join(parts)
        + ". Observation about delivery only; says nothing about honesty or competence."
    )


class DeliveryStore(Protocol):
    async def save(self, clerk_user_id: str, session_id: str, summary: DeliverySummary) -> bool:
        """Store the summary for a session the learner owns. False when there is no such session."""


class DbDeliveryStore:
    async def save(self, clerk_user_id: str, session_id: str, summary: DeliverySummary) -> bool:
        sid = parse_uuid(session_id)
        if sid is None:
            return False
        async with get_sessionmaker()() as db, db.begin():
            user_id: uuid.UUID | None = await db.scalar(
                select(User.id).where(
                    User.clerk_user_id == clerk_user_id, User.deleted_at.is_(None)
                )
            )
            if user_id is None:
                return False
            owned = await db.scalar(
                select(SessionRow.id).where(SessionRow.id == sid, SessionRow.user_id == user_id)
            )
            if owned is None:
                return False
            await MemoryStore(db).append(
                NewMemory(
                    user_id=user_id,
                    layer=MemoryLayer.SKILLS,
                    kind=DELIVERY_KIND,
                    content=describe(summary),
                    source=MemorySource.SYSTEM,
                    source_character=Character.VIDURA,
                    source_session_id=sid,
                    status=MemoryStatus.PROVISIONAL,
                    data={"consent": True, **summary.model_dump(exclude={"consent"})},
                )
            )
        return True


_store: DeliveryStore | None = None


def get_delivery_store() -> DeliveryStore:
    global _store
    if _store is None:
        _store = DbDeliveryStore()
    return _store


@router.post("/{session_id}/delivery", status_code=status.HTTP_204_NO_CONTENT)
async def post_delivery(
    session_id: str,
    body: DeliverySummary,
    learner: Annotated[Learner, Depends(current_learner)],
    store: Annotated[DeliveryStore, Depends(get_delivery_store)],
) -> None:
    if not await store.save(learner.user_id, session_id, body):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
