"""Learner-facing Drona routes: the live growth stream and the session lifecycle.

- `GET /v1/live/growth`: server-sent events of the signed-in learner's garden activity. Open
  streams in every tab receive the same events, so the dashboard glows while a session runs in
  another tab. The browser reaches it through the Next route handler (EventSource cannot send an
  Authorization header).
- `POST /v1/sessions/{id}/end`: the browser reports a hang-up, so an interrupted call is closed
  even if the provider webhook is late.
- `PUT /v1/sessions/{id}/conversation`: the browser reports the ElevenLabs conversation ID when
  the token response did not carry one.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from sg_api.drona.growth import GrowthFeed, get_growth_feed, sse_stream
from sg_api.drona.store import SessionStore, get_session_store
from sg_api.sessions.identity import Learner, current_learner
from sg_core.models.enums import SessionStatus

router = APIRouter(prefix="/v1", tags=["drona"])


@router.get("/live/growth")
async def live_growth(
    request: Request,
    learner: Annotated[Learner, Depends(current_learner)],
    feed: Annotated[GrowthFeed, Depends(get_growth_feed)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    # Resume after a reconnect from the last event the browser saw; otherwise only new events.
    cursor = last_event_id if last_event_id and last_event_id.isdigit() else None
    if cursor is None:
        cursor = await feed.latest_cursor(learner.user_id)
    return StreamingResponse(
        sse_stream(feed, learner.user_id, cursor, is_disconnected=request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )


class EndSessionRequest(BaseModel):
    status: Literal["completed", "interrupted"] = "completed"


@router.post("/sessions/{session_id}/end", status_code=status.HTTP_204_NO_CONTENT)
async def end_session(
    session_id: str,
    body: EndSessionRequest,
    learner: Annotated[Learner, Depends(current_learner)],
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> None:
    if not await store.end(learner.user_id, session_id, SessionStatus(body.status)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")


class BindConversationRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=128)


@router.put("/sessions/{session_id}/conversation", status_code=status.HTTP_204_NO_CONTENT)
async def bind_conversation(
    session_id: str,
    body: BindConversationRequest,
    learner: Annotated[Learner, Depends(current_learner)],
    store: Annotated[SessionStore, Depends(get_session_store)],
) -> None:
    result = await store.bind_conversation(learner.user_id, session_id, body.conversation_id)
    if result == "missing":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    if result == "conflict":
        raise HTTPException(status.HTTP_409_CONFLICT, "session already has another conversation")
