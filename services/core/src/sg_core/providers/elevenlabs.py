"""Minimal async ElevenLabs REST client.

Covers what C06 needs: WebRTC conversation tokens for private agents and Voice Design. C03
extends this adapter with usage-ledger recording and budget reservations; keep it free of
business logic.
"""

from types import TracebackType
from typing import Any, Self

import httpx
from pydantic import BaseModel, SecretStr

DEFAULT_BASE_URL = "https://api.elevenlabs.io"


class ElevenLabsError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"ElevenLabs API error {status_code}: {detail}")
        self.status_code = status_code


class ConversationToken(BaseModel):
    """GET /v1/convai/conversation/token. The conversation ID is known before the call starts."""

    token: str
    conversation_id: str | None = None


class VoicePreview(BaseModel):
    generated_voice_id: str
    audio_base_64: str
    media_type: str = "audio/mpeg"
    duration_secs: float | None = None


class VoiceDesignResult(BaseModel):
    previews: list[VoicePreview]
    text: str


class ElevenLabsClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"xi-api-key": api_key.get_secret_value()},
            timeout=timeout,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._http.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise ElevenLabsError(response.status_code, response.text[:500])
        return response.json()

    async def get_conversation_token(
        self,
        agent_id: str,
        *,
        participant_name: str | None = None,
        branch_id: str | None = None,
        environment: str | None = None,
    ) -> ConversationToken:
        params = {
            key: value
            for key, value in {
                "agent_id": agent_id,
                "participant_name": participant_name,
                "branch_id": branch_id,
                "environment": environment,
            }.items()
            if value is not None
        }
        data = await self._request("GET", "/v1/convai/conversation/token", params=params)
        return ConversationToken.model_validate(data)

    async def design_voice(
        self,
        *,
        voice_description: str,
        text: str,
        model_id: str = "eleven_ttv_v3",
        guidance_scale: float = 5.0,
        loudness: float = 0.5,
        seed: int | None = None,
    ) -> VoiceDesignResult:
        body = {
            "voice_description": voice_description,
            "text": text,
            "model_id": model_id,
            "guidance_scale": guidance_scale,
            "loudness": loudness,
            "seed": seed,
        }
        data = await self._request("POST", "/v1/text-to-voice/design", json=body, timeout=120.0)
        return VoiceDesignResult.model_validate(data)

    async def create_voice_from_preview(
        self,
        *,
        voice_name: str,
        voice_description: str,
        generated_voice_id: str,
        labels: dict[str, str] | None = None,
    ) -> str:
        body = {
            "voice_name": voice_name,
            "voice_description": voice_description,
            "generated_voice_id": generated_voice_id,
            "labels": labels,
        }
        data = await self._request("POST", "/v1/text-to-voice", json=body)
        voice_id: str = data["voice_id"]
        return voice_id


def client_from_settings() -> ElevenLabsClient:
    """Build a client from `Settings`; raises if no API key is configured."""
    from sg_core.settings import get_settings

    settings = get_settings()
    if settings.elevenlabs_api_key is None:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")
    return ElevenLabsClient(settings.elevenlabs_api_key, base_url=settings.elevenlabs_base_url)
