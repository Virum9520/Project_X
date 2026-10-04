import hashlib
import hmac
import json

import pytest
from pydantic import SecretStr

from sg_core.webhooks import (
    ElevenLabsVerifier,
    SignatureError,
    UnknownProviderError,
    VerifierRegistry,
)

SECRET = "whsec_test"
NOW = 1_700_000_000.0


def sign(body: bytes, ts: int = int(NOW), secret: str = SECRET) -> dict[str, str]:
    mac = hmac.new(secret.encode(), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"elevenlabs-signature": f"t={ts},v0={mac}"}


def verifier(secret: str | None = SECRET) -> ElevenLabsVerifier:
    return ElevenLabsVerifier(SecretStr(secret) if secret else None, now=lambda: NOW)


BODY = json.dumps(
    {"type": "post_call_transcription", "data": {"conversation_id": "conv_1", "transcript": []}}
).encode()


def test_valid_signature_passes_and_parses() -> None:
    v = verifier()
    v.verify(sign(BODY), BODY)
    parsed = v.parse(BODY)
    assert parsed.event_id == "post_call_transcription:conv_1"
    assert parsed.event_type == "post_call_transcription"


def test_header_lookup_is_case_insensitive() -> None:
    verifier().verify({"ElevenLabs-Signature": sign(BODY)["elevenlabs-signature"]}, BODY)


@pytest.mark.parametrize(
    ("headers", "body"),
    [
        ({}, BODY),
        ({"elevenlabs-signature": "garbage"}, BODY),
        ({"elevenlabs-signature": "t=abc,v0=00"}, BODY),
        (sign(BODY, secret="other"), BODY),
        (sign(BODY), BODY + b" "),  # body tampered
        (sign(BODY, ts=int(NOW) - 3600), BODY),  # replay outside tolerance
        (sign(BODY, ts=int(NOW) + 3600), BODY),
    ],
)
def test_bad_signatures_are_rejected(headers: dict[str, str], body: bytes) -> None:
    with pytest.raises(SignatureError):
        verifier().verify(headers, body)


def test_missing_secret_rejects_everything() -> None:
    with pytest.raises(SignatureError):
        verifier(None).verify(sign(BODY), BODY)


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"type":"x"}', b'{"data":{}}'])
def test_unparseable_payloads_raise(body: bytes) -> None:
    with pytest.raises(SignatureError):
        verifier().parse(body)


def test_registry_is_pluggable() -> None:
    registry = VerifierRegistry()
    registry.register(verifier())
    assert registry.providers() == ["elevenlabs"]
    assert registry.get("elevenlabs").provider == "elevenlabs"
    with pytest.raises(UnknownProviderError):
        registry.get("twilio")
