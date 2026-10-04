"""`CallChannel`: how an intended call actually reaches the learner.

`WebCallChannel` is implemented: it rings the learner's browser with a Web Push notification
("Incoming call from Bhima") and the app's incoming-call screen; accepting starts an ElevenLabs
WebRTC session (see `sg_api.accountability`). An unanswered call times out to `missed` and is not
redialled. `PhoneCallChannel` is only the adapter shape for a later telephony relay (Twilio, SIP
trunk or ElevenLabs' outbound API); with no relay it reports a clean failure.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sg_core.accountability.store import AccountabilityStore
from sg_core.logging import get_logger
from sg_core.models.enums import CallChannelKind, CallState
from sg_core.settings import Settings

log = get_logger(__name__)

CALLER_NAME = "Bhima"


@dataclass(frozen=True, slots=True)
class DispatchRequest:
    attempt_id: uuid.UUID
    occurrence_id: uuid.UUID
    user_id: uuid.UUID
    max_duration_seconds: int
    destination: str | None = None  # E.164, phone channel only
    tone: str | None = None


@dataclass(frozen=True, slots=True)
class DispatchResult:
    state: CallState
    error: str | None = None
    # Provider identifiers to record on the attempt: `el_conversation_id`, `twilio_call_sid`.
    attempt_fields: dict[str, Any] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)


class CallChannel(Protocol):
    kind: CallChannelKind

    async def dispatch(self, request: DispatchRequest) -> DispatchResult:
        """Start the call. `RINGING` on success; `FAILED`/`BUSY` otherwise. Never redials."""
        ...

    async def cancel(self, attempt_id: uuid.UUID) -> None:
        """Stop a call that has not connected (best effort)."""
        ...


# ── Web ──
class PushError(RuntimeError):
    pass


class PushGoneError(PushError):
    """The browser has unsubscribed (HTTP 404/410): drop the subscription."""


@dataclass(frozen=True, slots=True)
class PushTarget:
    endpoint: str
    p256dh: str
    auth: str


class PushSender(Protocol):
    async def send(self, target: PushTarget, payload: dict[str, Any], ttl_seconds: int) -> None: ...


class VapidPushSender:
    """Web Push over VAPID using `pywebpush` (blocking, so run off the event loop)."""

    def __init__(self, public_key: str, private_key: str, subject: str) -> None:
        self.public_key = public_key
        self._private_key = private_key
        self._subject = subject

    async def send(self, target: PushTarget, payload: dict[str, Any], ttl_seconds: int) -> None:
        await asyncio.to_thread(self._send_blocking, target, payload, ttl_seconds)

    def _send_blocking(self, target: PushTarget, payload: dict[str, Any], ttl_seconds: int) -> None:
        from pywebpush import WebPushException, webpush

        try:
            webpush(
                subscription_info={
                    "endpoint": target.endpoint,
                    "keys": {"p256dh": target.p256dh, "auth": target.auth},
                },
                data=json.dumps(payload),
                vapid_private_key=self._private_key,
                vapid_claims={"sub": self._subject},
                ttl=ttl_seconds,
                headers={"Urgency": "high"},
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                raise PushGoneError(str(exc)) from exc
            raise PushError(str(exc)) from exc


def push_sender_from_settings(settings: Settings) -> PushSender | None:
    """None until VAPID keys are configured (the in-app incoming-call poll still works)."""
    if settings.vapid_public_key and settings.vapid_private_key is not None:
        return VapidPushSender(
            settings.vapid_public_key,
            settings.vapid_private_key.get_secret_value(),
            settings.vapid_subject,
        )
    return None


class WebCallChannel:
    kind = CallChannelKind.WEB

    def __init__(
        self,
        store: AccountabilityStore,
        push: PushSender | None,
        *,
        ring_timeout_seconds: int,
    ) -> None:
        self._store = store
        self._push = push
        self.ring_timeout_seconds = ring_timeout_seconds

    async def dispatch(self, request: DispatchRequest) -> DispatchResult:
        expires_at = datetime.now(UTC) + timedelta(seconds=self.ring_timeout_seconds)
        payload = {
            "type": "incoming_call",
            "title": f"Incoming call from {CALLER_NAME}",
            "body": "Tap to answer. It takes about two minutes.",
            "attempt_id": str(request.attempt_id),
            "caller": CALLER_NAME,
            "expires_at": expires_at.isoformat(),
            "max_duration_seconds": request.max_duration_seconds,
            "url": f"/call/{request.attempt_id}",
        }
        delivered = 0
        subscriptions = await self._store.list_push_subscriptions(request.user_id)
        if self._push is not None:
            for sub in subscriptions:
                try:
                    await self._push.send(
                        PushTarget(sub.endpoint, sub.p256dh, sub.auth),
                        payload,
                        self.ring_timeout_seconds,
                    )
                    delivered += 1
                except PushGoneError:
                    await self._store.revoke_push_subscription(sub.endpoint)
                except PushError as exc:
                    log.warning(
                        "web_call.push_failed", attempt_id=str(request.attempt_id), error=str(exc)
                    )
        # The call rings even with no push delivered: an open app sees it via the incoming-call
        # poll. If nobody answers within the timeout it becomes `missed`.
        return DispatchResult(
            state=CallState.RINGING,
            detail={"push_delivered": delivered, "push_subscriptions": len(subscriptions)},
        )

    async def cancel(self, attempt_id: uuid.UUID) -> None:
        # Nothing to tear down: a cancelled attempt stops being offered by the incoming-call poll
        # and the accept endpoint refuses it. A late push notification opens an expired screen.
        return None


# ── Phone (stub) ──
@dataclass(frozen=True, slots=True)
class PhoneCallHandle:
    conversation_id: str | None
    call_sid: str | None


class PhoneRelay(Protocol):
    """Adapter a future telephony integration implements (Twilio, SIP, ElevenLabs outbound)."""

    async def place_call(self, destination: str, max_duration_seconds: int) -> PhoneCallHandle: ...

    async def hang_up(self, call_sid: str) -> None: ...


class PhoneCallChannel:
    """Interface only. Without a relay every dispatch fails cleanly with a stable error code."""

    kind = CallChannelKind.PHONE
    NOT_IMPLEMENTED = "phone_channel_not_implemented"

    def __init__(self, relay: PhoneRelay | None = None) -> None:
        self._relay = relay

    async def dispatch(self, request: DispatchRequest) -> DispatchResult:
        if self._relay is None or not request.destination:
            return DispatchResult(state=CallState.FAILED, error=self.NOT_IMPLEMENTED)
        handle = await self._relay.place_call(request.destination, request.max_duration_seconds)
        return DispatchResult(
            state=CallState.RINGING,
            attempt_fields={
                "el_conversation_id": handle.conversation_id,
                "twilio_call_sid": handle.call_sid,
            },
        )

    async def cancel(self, attempt_id: uuid.UUID) -> None:
        return None
