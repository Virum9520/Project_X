"""Minimal async ElevenLabs REST client.

Covers conversation tokens for private agents, Voice Design (C06), and the metered media calls
(speech, sound effects, music, Scribe) plus conversation cost metadata (C03). Metered methods take
an optional `usage=UsageContext(...)`; when the client has a recorder they report what they
consumed to the usage ledger. Budget holds are the caller's job (`sg_core.economics.budget_hold`);
keep this adapter free of business logic.
"""

from decimal import Decimal
from types import TracebackType
from typing import Any, Self

import httpx
from pydantic import BaseModel, SecretStr

from sg_core.economics.usage import NullUsageRecorder, UsageContext, UsageMeasure, UsageRecorder

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


class AudioResult(BaseModel):
    audio: bytes
    media_type: str = "audio/mpeg"


class Transcript(BaseModel):
    text: str
    language_code: str | None = None
    duration_secs: float | None = None


class ConversationDetails(BaseModel):
    conversation_id: str
    agent_id: str | None = None
    status: str | None = None
    call_duration_secs: float | None = None
    metadata: dict[str, Any] = {}


class ElevenLabsClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        recorder: UsageRecorder | None = None,
    ) -> None:
        self._recorder: UsageRecorder = recorder or NullUsageRecorder()
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

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._http.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise ElevenLabsError(response.status_code, response.text[:500])
        return response

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        return (await self._send(method, path, **kwargs)).json()

    async def _report(self, usage: UsageContext | None, measure: UsageMeasure) -> None:
        if usage is not None:
            await self._recorder.record(usage, measure)

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
        usage: UsageContext | None = None,
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
        await self._report(
            usage,
            UsageMeasure(
                provider="elevenlabs",
                model=model_id,
                billable_units=Decimal(1),
                billable_unit="voice_design",
            ),
        )
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

    async def text_to_speech(
        self,
        voice_id: str,
        text: str,
        *,
        model_id: str = "eleven_flash_v2_5",
        output_format: str = "mp3_44100_128",
        usage: UsageContext | None = None,
    ) -> AudioResult:
        response = await self._send(
            "POST",
            f"/v1/text-to-speech/{voice_id}",
            params={"output_format": output_format},
            json={"text": text, "model_id": model_id},
            timeout=120.0,
        )
        await self._report(
            usage,
            UsageMeasure(
                provider="elevenlabs",
                model=model_id,
                external_ref=response.headers.get("request-id"),
                billable_units=Decimal(len(text)),
                billable_unit="tts_character",
                raw={"character_cost": response.headers.get("character-cost")},
            ),
        )
        return AudioResult(audio=response.content, media_type=_media_type(response))

    async def generate_sound_effect(
        self,
        text: str,
        *,
        duration_seconds: float | None = None,
        prompt_influence: float | None = None,
        loop: bool = False,
        usage: UsageContext | None = None,
    ) -> AudioResult:
        body = {
            "text": text,
            "duration_seconds": duration_seconds,
            "prompt_influence": prompt_influence,
            "loop": loop,
        }
        response = await self._send(
            "POST",
            "/v1/sound-generation",
            json={k: v for k, v in body.items() if v is not None},
            timeout=120.0,
        )
        # Auto-duration effects have no known length, so they stay unpriced (NULL, not zero).
        await self._report(
            usage,
            UsageMeasure(
                provider="elevenlabs",
                external_ref=response.headers.get("request-id"),
                billable_units=None if duration_seconds is None else Decimal(str(duration_seconds)),
                billable_unit="sound_generation_second",
            ),
        )
        return AudioResult(audio=response.content, media_type=_media_type(response))

    async def compose_music(
        self,
        prompt: str,
        *,
        length_ms: int,
        model_id: str = "music_v1",
        usage: UsageContext | None = None,
    ) -> AudioResult:
        response = await self._send(
            "POST",
            "/v1/music",
            json={"prompt": prompt, "music_length_ms": length_ms, "model_id": model_id},
            timeout=300.0,
        )
        await self._report(
            usage,
            UsageMeasure(
                provider="elevenlabs",
                model=model_id,
                external_ref=response.headers.get("request-id"),
                billable_units=Decimal(length_ms) / 1000,
                billable_unit="music_second",
            ),
        )
        return AudioResult(audio=response.content, media_type=_media_type(response))

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str = "audio.webm",
        content_type: str = "audio/webm",
        model_id: str = "scribe_v1",
        language_code: str | None = None,
        usage: UsageContext | None = None,
    ) -> Transcript:
        """Scribe speech-to-text (used for the Future-Self consent phrase check)."""
        data = {"model_id": model_id, **({"language_code": language_code} if language_code else {})}
        payload = await self._request(
            "POST",
            "/v1/speech-to-text",
            data=data,
            files={"file": (filename, audio, content_type)},
            timeout=300.0,
        )
        words = payload.get("words") or []
        duration = max((w["end"] for w in words if w.get("end") is not None), default=None)
        await self._report(
            usage,
            UsageMeasure(
                provider="elevenlabs",
                model=model_id,
                billable_units=None if duration is None else Decimal(str(duration)),
                billable_unit="speech_to_text_second",
            ),
        )
        return Transcript(
            text=payload.get("text", ""),
            language_code=payload.get("language_code"),
            duration_secs=duration,
        )

    async def get_conversation(self, conversation_id: str) -> ConversationDetails:
        data = await self._request("GET", f"/v1/convai/conversations/{conversation_id}")
        metadata = data.get("metadata") or {}
        return ConversationDetails(
            conversation_id=data.get("conversation_id", conversation_id),
            agent_id=data.get("agent_id"),
            status=data.get("status"),
            call_duration_secs=metadata.get("call_duration_secs"),
            metadata=metadata,
        )

    async def record_conversation_usage(
        self, conversation_id: str, usage: UsageContext
    ) -> ConversationDetails:
        """Fetch a finished conversation and ledger its connected time (agent-minute estimate).

        Idempotent per conversation unless `usage.idempotency_key` says otherwise. The raw
        metadata (charging, LLM usage) is kept so reconciliation can replace the estimate.
        """
        details = await self.get_conversation(conversation_id)
        if details.call_duration_secs is not None:
            key = usage.idempotency_key or f"elevenlabs:conversation:{conversation_id}"
            await self._recorder.record(
                UsageContext(
                    cost_center=usage.cost_center,
                    component=usage.component,
                    user_id=usage.user_id,
                    session_id=usage.session_id,
                    idempotency_key=key,
                    environment=usage.environment,
                ),
                UsageMeasure(
                    provider="elevenlabs",
                    external_ref=conversation_id,
                    connected_seconds=Decimal(str(details.call_duration_secs)),
                    raw={"metadata": details.metadata, "agent_id": details.agent_id},
                ),
            )
        return details


def _media_type(response: httpx.Response) -> str:
    return str(response.headers.get("content-type", "audio/mpeg")).split(";")[0]


def client_from_settings() -> ElevenLabsClient:
    """Build a client from `Settings`; raises if no API key is configured."""
    from sg_core.settings import get_settings

    settings = get_settings()
    if settings.elevenlabs_api_key is None:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")
    from sg_core.economics.ledger import DbUsageRecorder

    return ElevenLabsClient(
        settings.elevenlabs_api_key,
        base_url=settings.elevenlabs_base_url,
        recorder=DbUsageRecorder(),
    )
