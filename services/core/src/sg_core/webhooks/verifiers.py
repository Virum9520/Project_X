"""Pluggable webhook signature verifiers, one per provider."""

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import SecretStr

from sg_core.settings import Settings

ELEVENLABS_TOLERANCE_SECONDS = 30 * 60


class SignatureError(Exception):
    """Signature missing, malformed, stale or wrong. Never carries secret material."""


class UnknownProviderError(KeyError):
    pass


@dataclass(frozen=True)
class ParsedEvent:
    event_id: str
    event_type: str
    payload: dict[str, Any]


class WebhookVerifier(Protocol):
    provider: str

    def verify(self, headers: Mapping[str, str], body: bytes) -> None:
        """Raise SignatureError unless the request is authentic and fresh."""

    def parse(self, body: bytes) -> ParsedEvent:
        """Extract a stable provider event id and type. Called only after verify()."""


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


class ElevenLabsVerifier:
    """`ElevenLabs-Signature: t=<unix>,v0=<hex>` where v0 = HMAC-SHA256(secret, f"{t}.{body}")."""

    provider = "elevenlabs"

    def __init__(
        self,
        secret: SecretStr | None,
        *,
        tolerance_seconds: int = ELEVENLABS_TOLERANCE_SECONDS,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._secret = secret
        self._tolerance = tolerance_seconds
        self._now = now

    def verify(self, headers: Mapping[str, str], body: bytes) -> None:
        if self._secret is None:
            raise SignatureError("webhook secret not configured")
        header = _header(headers, "ElevenLabs-Signature")
        if not header:
            raise SignatureError("missing signature header")
        parts = dict(p.strip().split("=", 1) for p in header.split(",") if "=" in p)
        timestamp, provided = parts.get("t"), parts.get("v0")
        if not timestamp or not provided or not timestamp.isdigit():
            raise SignatureError("malformed signature header")
        if abs(self._now() - int(timestamp)) > self._tolerance:
            raise SignatureError("timestamp outside tolerance")
        expected = hmac.new(
            self._secret.get_secret_value().encode(),
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, provided):
            raise SignatureError("signature mismatch")

    def parse(self, body: bytes) -> ParsedEvent:
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise SignatureError("body is not JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
            raise SignatureError("payload has no event type")
        data = payload.get("data")
        conversation_id = data.get("conversation_id") if isinstance(data, dict) else None
        if not isinstance(conversation_id, str) or not conversation_id:
            raise SignatureError("payload has no conversation_id")
        event_type = payload["type"]
        # One event per (type, conversation): ElevenLabs retries re-send the same pair.
        return ParsedEvent(f"{event_type}:{conversation_id}", event_type, payload)


class VerifierRegistry:
    def __init__(self) -> None:
        self._verifiers: dict[str, WebhookVerifier] = {}

    def register(self, verifier: WebhookVerifier) -> None:
        self._verifiers[verifier.provider] = verifier

    def get(self, provider: str) -> WebhookVerifier:
        try:
            return self._verifiers[provider]
        except KeyError:
            raise UnknownProviderError(provider) from None

    def providers(self) -> list[str]:
        return sorted(self._verifiers)


def default_registry(settings: Settings) -> VerifierRegistry:
    """Add future providers (twilio, clerk, e2b) here."""
    registry = VerifierRegistry()
    registry.register(ElevenLabsVerifier(settings.elevenlabs_webhook_secret))
    return registry
