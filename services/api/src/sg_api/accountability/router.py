"""Learner-facing accountability API: call schedules, Web Push, and the incoming-call flow.

Auth is the learner's Clerk session (`current_learner`). Everything is scoped to the caller's own
`users` row; other people's schedules and calls answer 404.

Incoming call (WebCallChannel): the dispatcher rings (Web Push plus `GET /calls/incoming` for an
open app); the learner taps accept, which starts the Bhima ElevenLabs session with a capped
duration and a retention question; the client reports `end` (the sweeper is the backstop).
"""

import uuid
from datetime import UTC, datetime, time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field

from sg_api.accountability.deps import (
    DEFAULT_TZ,
    UserDirectory,
    UserRef,
    get_accountability_store,
    get_dispatcher,
    get_policy,
    get_retention_source,
    get_user_directory,
)
from sg_api.sessions.briefing import BriefingProvider, get_briefing_provider
from sg_api.sessions.identity import Learner, current_learner
from sg_api.sessions.router import (
    SessionStartRequest,
    SessionStartResponse,
    get_elevenlabs,
    start_session,
)
from sg_core.accountability import (
    AccountabilityStore,
    CallDispatcher,
    CallNotAcceptable,
    DispatchPolicy,
    RetentionSource,
    ScheduleRejected,
    ScheduleSpec,
    create_schedule,
    delete_schedule,
    plan_retention,
    retention_variables,
    update_schedule,
)
from sg_core.logging import get_logger
from sg_core.models.accountability import CallSchedule
from sg_core.models.enums import CallChannelKind, CallState, CommitmentStatus
from sg_core.providers.elevenlabs import ElevenLabsClient
from sg_core.settings import Settings, get_settings

router = APIRouter(prefix="/v1/accountability", tags=["accountability"])
log = get_logger(__name__)

# Seconds before the cap at which the client asks Bhima to wrap up gracefully.
WRAP_UP_LEAD_SECONDS = 20


async def current_user(
    learner: Annotated[Learner, Depends(current_learner)],
    users: Annotated[UserDirectory, Depends(get_user_directory)],
) -> UserRef:
    user = await users.resolve(learner.user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "finish onboarding first")
    return user


CurrentUser = Annotated[UserRef, Depends(current_user)]
Store = Annotated[AccountabilityStore, Depends(get_accountability_store)]
Dispatcher = Annotated[CallDispatcher, Depends(get_dispatcher)]
Policy = Annotated[DispatchPolicy, Depends(get_policy)]


# ── config ──
class AccountabilityConfig(BaseModel):
    consent_version: str
    quiet_start: str
    quiet_end: str
    ring_timeout_seconds: int
    vapid_public_key: str | None
    phone_available: bool = False


@router.get("/config", response_model=AccountabilityConfig)
async def config(
    _: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
    policy: Policy,
) -> AccountabilityConfig:
    return AccountabilityConfig(
        consent_version=policy.consent_version,
        quiet_start=policy.quiet_start,
        quiet_end=policy.quiet_end,
        ring_timeout_seconds=int(policy.ring_timeout.total_seconds()),
        vapid_public_key=settings.vapid_public_key,
    )


# ── schedules ──
class ScheduleBody(BaseModel):
    tz: str = Field(max_length=64)
    local_time: time
    days: list[int] = Field(min_length=1, max_length=7)
    tone: Literal["energetic", "calm"] | None = None
    max_duration_seconds: int = 120
    consent_version: str = Field(max_length=32)
    enabled: bool = True


class ScheduleOut(BaseModel):
    id: str
    channel: CallChannelKind
    tz: str
    local_time: str
    days: list[int]
    tone: str | None
    max_duration_seconds: int
    enabled: bool
    consent_version: str


def _out(s: CallSchedule) -> ScheduleOut:
    return ScheduleOut(
        id=str(s.id),
        channel=s.channel,
        tz=s.tz,
        local_time=s.local_time.strftime("%H:%M"),
        days=list(s.days),
        tone=s.tone,
        max_duration_seconds=s.max_duration_seconds,
        enabled=s.enabled,
        consent_version=s.consent_ver,
    )


def _spec(body: ScheduleBody) -> ScheduleSpec:
    return ScheduleSpec(
        tz=body.tz,
        local_time=body.local_time,
        days=body.days,
        channel=CallChannelKind.WEB,
        tone=body.tone,
        max_duration_seconds=body.max_duration_seconds,
        consent_ver=body.consent_version,
        enabled=body.enabled,
    )


def _rejected(exc: ScheduleRejected) -> HTTPException:
    return HTTPException(422, {"code": exc.code, "message": str(exc)})


@router.get("/schedules", response_model=list[ScheduleOut])
async def list_schedules(user: CurrentUser, store: Store) -> list[ScheduleOut]:
    return [_out(s) for s in await store.list_schedules(user.id)]


@router.post("/schedules", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
async def add_schedule(
    body: ScheduleBody, user: CurrentUser, store: Store, policy: Policy
) -> ScheduleOut:
    try:
        return _out(await create_schedule(store, user.id, _spec(body), policy))
    except ScheduleRejected as exc:
        raise _rejected(exc) from exc


@router.put("/schedules/{schedule_id}", response_model=ScheduleOut)
async def replace_schedule(
    schedule_id: uuid.UUID, body: ScheduleBody, user: CurrentUser, store: Store, policy: Policy
) -> ScheduleOut:
    try:
        updated = await update_schedule(store, user.id, schedule_id, _spec(body), policy)
    except ScheduleRejected as exc:
        raise _rejected(exc) from exc
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "schedule not found")
    return _out(updated)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_schedule(schedule_id: uuid.UUID, user: CurrentUser, store: Store) -> Response:
    if not await delete_schedule(store, user.id, schedule_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "schedule not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── push subscriptions ──
class PushKeys(BaseModel):
    p256dh: str = Field(max_length=256)
    auth: str = Field(max_length=128)


class PushSubscriptionBody(BaseModel):
    endpoint: str = Field(max_length=2000, pattern=r"^https://")
    keys: PushKeys


@router.post("/push-subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe_push(
    body: PushSubscriptionBody,
    user: CurrentUser,
    store: Store,
    user_agent: Annotated[str | None, Header(max_length=300)] = None,
) -> Response:
    await store.upsert_push_subscription(
        user_id=user.id,
        endpoint=body.endpoint,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        user_agent=user_agent,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class PushUnsubscribeBody(BaseModel):
    endpoint: str = Field(max_length=2000)


@router.post("/push-subscriptions/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_push(body: PushUnsubscribeBody, user: CurrentUser, store: Store) -> Response:
    owned = {s.endpoint for s in await store.list_push_subscriptions(user.id)}
    if body.endpoint in owned:
        await store.revoke_push_subscription(body.endpoint)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── commitments (read only; Bhima writes them through the agent tools) ──
class CommitmentOut(BaseModel):
    id: str
    description: str
    due_at: datetime | None
    status: CommitmentStatus
    completion_source: str | None
    reported_status: str | None


@router.get("/commitments", response_model=list[CommitmentOut])
async def list_commitments(user: CurrentUser, store: Store) -> list[CommitmentOut]:
    return [
        CommitmentOut(
            id=str(c.id),
            description=c.description,
            due_at=c.due_at,
            status=c.status,
            completion_source=c.completion_source.value if c.completion_source else None,
            reported_status=c.reported_status,
        )
        for c in await store.list_commitments(user.id)
    ]


# ── incoming calls ──
class IncomingCall(BaseModel):
    attempt_id: str
    caller: str = "Bhima"
    expires_at: datetime
    max_duration_seconds: int


class IncomingCallResponse(BaseModel):
    call: IncomingCall | None


async def _cap_for(
    store: AccountabilityStore, attempt_id: uuid.UUID, policy: DispatchPolicy
) -> int:
    attempt = await store.get_attempt(attempt_id)
    occurrence = await store.get_occurrence(attempt.occurrence_id) if attempt else None
    schedule = (
        await store.get_schedule(occurrence.schedule_id)
        if occurrence is not None and occurrence.schedule_id
        else None
    )
    return schedule.max_duration_seconds if schedule else policy.default_max_duration_seconds


@router.get("/calls/incoming", response_model=IncomingCallResponse)
async def incoming_call(user: CurrentUser, store: Store, policy: Policy) -> IncomingCallResponse:
    """What an open app polls (every few seconds) as the fallback when push is unavailable."""
    attempt = await store.ringing_attempt_for_user(user.id)
    if attempt is None or attempt.dispatched_at is None:
        return IncomingCallResponse(call=None)
    expires_at = attempt.dispatched_at + policy.ring_timeout
    if expires_at <= datetime.now(UTC):
        return IncomingCallResponse(call=None)
    return IncomingCallResponse(
        call=IncomingCall(
            attempt_id=str(attempt.id),
            expires_at=expires_at,
            max_duration_seconds=await _cap_for(store, attempt.id, policy),
        )
    )


class AcceptedCall(BaseModel):
    attempt_id: str
    session: SessionStartResponse
    max_duration_seconds: int
    # Ask Bhima to wrap up and end the call at these offsets from the start of the conversation.
    wrap_up_after_seconds: int
    hard_stop_after_seconds: int
    retention_concept: str | None


_ACCEPT_ERRORS = {
    "not_found": (status.HTTP_404_NOT_FOUND, "call not found"),
    "not_ringing": (status.HTTP_409_CONFLICT, "this call is no longer ringing"),
    "expired": (status.HTTP_410_GONE, "this call has ended"),
}


@router.post("/calls/{attempt_id}/accept", response_model=AcceptedCall)
async def accept_call(
    attempt_id: uuid.UUID,
    learner: Annotated[Learner, Depends(current_learner)],
    user: CurrentUser,
    store: Store,
    dispatcher: Dispatcher,
    policy: Policy,
    settings: Annotated[Settings, Depends(get_settings)],
    briefings: Annotated[BriefingProvider, Depends(get_briefing_provider)],
    elevenlabs: Annotated[ElevenLabsClient, Depends(get_elevenlabs)],
    retention: Annotated[RetentionSource, Depends(get_retention_source)],
) -> AcceptedCall:
    try:
        await dispatcher.accept(attempt_id, user.id)
    except CallNotAcceptable as exc:
        code, detail = _ACCEPT_ERRORS.get(exc.reason, (status.HTTP_409_CONFLICT, exc.reason))
        raise HTTPException(code, detail) from exc

    cap = await _cap_for(store, attempt_id, policy)
    try:
        session = await start_session(
            SessionStartRequest(character="bhima"),
            learner.model_copy(update={"timezone": user.timezone or DEFAULT_TZ}),
            settings,
            briefings,
            elevenlabs,
        )
    except HTTPException as exc:
        await dispatcher.fail_connected(attempt_id, f"session_start_failed:{exc.status_code}")
        raise
    await dispatcher.attach_conversation(attempt_id, session.conversation_id)

    plan = None
    try:
        plan = await plan_retention(retention, user.id)
        if plan is not None:
            await retention.record_request(user.id, plan, attempt_id)
    except Exception:  # a missing retention question must never block the call
        log.warning("accountability.retention_failed", attempt_id=str(attempt_id), exc_info=True)
        plan = None
    session.dynamic_variables.update(retention_variables(plan))
    return AcceptedCall(
        attempt_id=str(attempt_id),
        session=session,
        max_duration_seconds=cap,
        wrap_up_after_seconds=max(cap - WRAP_UP_LEAD_SECONDS, cap // 2),
        hard_stop_after_seconds=cap,
        retention_concept=plan.concept_key if plan else None,
    )


@router.post("/calls/{attempt_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_call(
    attempt_id: uuid.UUID, user: CurrentUser, dispatcher: Dispatcher
) -> Response:
    if not await dispatcher.decline(attempt_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class EndBody(BaseModel):
    duration_seconds: int | None = Field(default=None, ge=0, le=3600)


@router.post("/calls/{attempt_id}/end", status_code=status.HTTP_204_NO_CONTENT)
async def end_call(
    attempt_id: uuid.UUID,
    body: EndBody,
    user: CurrentUser,
    store: Store,
    dispatcher: Dispatcher,
) -> Response:
    attempt = await store.get_attempt(attempt_id)
    occurrence = await store.get_occurrence(attempt.occurrence_id) if attempt else None
    if attempt is None or occurrence is None or occurrence.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
    if attempt.state in (CallState.CONNECTED, CallState.UNKNOWN):
        await dispatcher.complete(attempt_id, duration_seconds=body.duration_seconds)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
