"""Generate, store and serve the weekly Sanjaya recap.

Storage is the `ObjectStore` (no table): `recaps/<user uuid>/<ISO week>/recap.json` plus
`narration.mp3`. Generation is idempotent per learner and week; `force` rebuilds it. The voice
spend is held against the learner's monthly budget; with no voice configured, no ElevenLabs key
or no budget left the recap is still produced as text with estimated timing (`audio_url=None`),
so the flythrough works silently with captions.

Private link: an HMAC token over (learner, week, nonce, expiry). The nonce is stored in the recap
and `unshare` rotates it, which revokes every link issued before.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from sg_api.garden.data import GardenData
from sg_api.recap.schemas import RecapOut, RecapSegmentOut
from sg_api.recap.script import SCRIPT_VERSION, RecapScript, build_script, iso_week
from sg_api.recap.timing import keyframes
from sg_core.economics.budget import (
    BudgetExceededError,
    budget_hold,
    budget_key_for,
    monthly_limit_usd,
)
from sg_core.economics.pricing import PriceBook
from sg_core.economics.usage import UsageContext
from sg_core.logging import get_logger
from sg_core.models.enums import CostCenter
from sg_core.providers.elevenlabs import TimedAudioResult
from sg_core.providers.storage import ObjectNotFoundError, ObjectStore

log = get_logger(__name__)

WEEK_RE = re.compile(r"\d{4}-W\d{2}")
SHARE_TTL = timedelta(days=7)
AUDIO_URL_TTL_SECONDS = 6 * 3600
UNPRICED_HOLD_USD = Decimal("0.10")


class RecapNotFound(LookupError):
    pass


class InvalidShareToken(ValueError):
    pass


class SpeechClient(Protocol):
    async def text_to_speech_with_timestamps(
        self, voice_id: str, text: str, *, usage: UsageContext | None = ...
    ) -> TimedAudioResult: ...


HoldFactory = Callable[[uuid.UUID, Decimal], AbstractAsyncContextManager[Any]]
ResolveUser = Callable[[str], Awaitable[uuid.UUID | None]]
LoadData = Callable[[uuid.UUID, datetime], Awaitable[GardenData]]


def learner_hold(user_id: uuid.UUID, amount_usd: Decimal) -> AbstractAsyncContextManager[Any]:
    return budget_hold(
        budget_key=budget_key_for(CostCenter.LEARNER, user_id),
        amount_usd=amount_usd,
        limit_usd=monthly_limit_usd(CostCenter.LEARNER),
        cost_center=CostCenter.LEARNER,
        user_id=user_id,
    )


def recap_prefix(user_id: uuid.UUID, week: str) -> str:
    return f"recaps/{user_id}/{week}/"


def estimate_speech_usd(text: str) -> Decimal:
    est = PriceBook().estimate("elevenlabs", [("tts_character", len(text))])
    return est.usd if est else UNPRICED_HOLD_USD


@dataclass(slots=True)
class RecapService:
    resolve_user: ResolveUser
    load_data: LoadData
    store: ObjectStore
    speech: SpeechClient | None
    voice_id: str | None
    secret: bytes | None
    hold: HoldFactory = learner_hold

    # ---- generation -------------------------------------------------------------------------

    async def generate(
        self, learner: str, *, now: datetime | None = None, force: bool = False
    ) -> RecapOut:
        now = now or datetime.now(UTC)
        user_id = await self.resolve_user(learner)
        if user_id is None:
            raise RecapNotFound("no recap for a learner without a garden yet")
        data = await self.load_data(user_id, now)
        script = build_script(data, now)
        prefix = recap_prefix(user_id, script.week)
        if not force:
            existing = await self._read(prefix)
            if existing is not None:
                return await self._render(existing, prefix)

        audio, alignment_frames = await self._speak(user_id, script, prefix)
        frames, duration_ms, timing = alignment_frames
        record: dict[str, Any] = {
            "script_version": SCRIPT_VERSION,
            "week": script.week,
            "week_start": script.week_start.isoformat(),
            "week_end": script.week_end.isoformat(),
            "generated_at": now.isoformat(),
            "narration": script.narration,
            "segments": [
                {
                    "id": s.id,
                    "kind": s.kind,
                    "text": s.text,
                    "focus": f.focus,
                    "concept_id": s.concept_key,
                    "evidence_ids": s.evidence_ids,
                    "start_ms": f.start_ms,
                    "end_ms": f.end_ms,
                }
                for s, f in zip(script.segments, frames, strict=True)
            ],
            "citations": script.citations,
            "duration_ms": duration_ms,
            "timing": timing,
            "quiet": script.quiet,
            "rules_version": script.rules_version,
            "audio_key": f"{prefix}narration.mp3" if audio else None,
            "share_nonce": None,
        }
        await self.store.put(
            f"{prefix}recap.json", json.dumps(record).encode(), content_type="application/json"
        )
        return await self._render(record, prefix)

    async def _speak(
        self, user_id: uuid.UUID, script: RecapScript, prefix: str
    ) -> tuple[bool, tuple[list[Any], int, str]]:
        if self.speech is None or not self.voice_id:
            return False, keyframes(script)
        usage = UsageContext(
            cost_center=CostCenter.LEARNER,
            component="sanjaya_recap",
            user_id=user_id,
            idempotency_key=f"recap:{user_id}:{script.week}:{hash_text(script.narration)}",
        )
        try:
            async with self.hold(user_id, estimate_speech_usd(script.narration)):
                result = await self.speech.text_to_speech_with_timestamps(
                    self.voice_id, script.narration, usage=usage
                )
        except BudgetExceededError:
            log.info("recap.budget_exceeded", user_id=str(user_id))
            return False, keyframes(script)
        except Exception:  # provider down or not configured: a text recap beats no recap
            log.warning("recap.speech_failed", exc_info=True)
            return False, keyframes(script)
        await self.store.put(f"{prefix}narration.mp3", result.audio, content_type=result.media_type)
        return True, keyframes(script, result.alignment)

    # ---- reading ----------------------------------------------------------------------------

    async def _read(self, prefix: str) -> dict[str, Any] | None:
        try:
            loaded: dict[str, Any] = json.loads((await self.store.get(f"{prefix}recap.json")).data)
        except (ObjectNotFoundError, ValueError):
            return None
        return loaded

    async def _render(self, record: dict[str, Any], prefix: str) -> RecapOut:
        audio_key = record.get("audio_key")
        return RecapOut(
            week=record["week"],
            week_start=record["week_start"],
            week_end=record["week_end"],
            generated_at=record["generated_at"],
            narration=record["narration"],
            segments=[RecapSegmentOut(**s) for s in record["segments"]],
            citations=record["citations"],
            duration_ms=record["duration_ms"],
            timing=record["timing"],
            quiet=record["quiet"],
            rules_version=record["rules_version"],
            audio_url=(
                await self.store.presigned_get_url(audio_key, expires_seconds=AUDIO_URL_TTL_SECONDS)
                if audio_key
                else None
            ),
            shared=bool(record.get("share_nonce")),
        )

    async def get(self, learner: str, week: str | None = None) -> RecapOut:
        user_id = await self.resolve_user(learner)
        if user_id is None:
            raise RecapNotFound(week or "latest")
        week = week or await self._latest_week(user_id)
        if week is None or not WEEK_RE.fullmatch(week):
            raise RecapNotFound(week or "latest")
        record = await self._read(recap_prefix(user_id, week))
        if record is None:
            raise RecapNotFound(week)
        return await self._render(record, recap_prefix(user_id, week))

    async def _latest_week(self, user_id: uuid.UUID) -> str | None:
        weeks = {k.split("/")[2] for k in await self.store.list_keys(f"recaps/{user_id}/")}
        return max(weeks, default=None)

    # ---- private links ----------------------------------------------------------------------

    def _sign(self, payload: str) -> str:
        if not self.secret:
            raise InvalidShareToken("sharing is not configured")
        return hmac.new(self.secret, payload.encode(), hashlib.sha256).hexdigest()[:40]

    async def share(
        self, learner: str, week: str, *, now: datetime | None = None
    ) -> tuple[str, datetime]:
        now = now or datetime.now(UTC)
        user_id = await self.resolve_user(learner)
        prefix = recap_prefix(user_id, week) if user_id and WEEK_RE.fullmatch(week) else ""
        record = await self._read(prefix) if prefix else None
        if user_id is None or record is None:
            raise RecapNotFound(week)
        if not record.get("share_nonce"):
            record["share_nonce"] = secrets.token_hex(8)
            await self.store.put(
                f"{prefix}recap.json", json.dumps(record).encode(), content_type="application/json"
            )
        expires = now + SHARE_TTL
        body = f"{user_id}|{week}|{record['share_nonce']}|{int(expires.timestamp())}"
        raw = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
        return f"{raw}.{self._sign(body)}", expires

    async def unshare(self, learner: str, week: str) -> None:
        user_id = await self.resolve_user(learner)
        prefix = recap_prefix(user_id, week) if user_id and WEEK_RE.fullmatch(week) else ""
        record = await self._read(prefix) if prefix else None
        if user_id is None or record is None:
            raise RecapNotFound(week)
        record["share_nonce"] = None
        await self.store.put(
            f"{prefix}recap.json", json.dumps(record).encode(), content_type="application/json"
        )

    async def open_shared(self, token: str, *, now: datetime | None = None) -> RecapOut:
        now = now or datetime.now(UTC)
        try:
            raw, sig = token.split(".", 1)
            body = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
            user_s, week, nonce, expiry = body.split("|")
            user_id = uuid.UUID(user_s)
            expired = now.timestamp() > int(expiry)
        except (ValueError, UnicodeDecodeError) as exc:
            raise InvalidShareToken("malformed link") from exc
        if not hmac.compare_digest(sig, self._sign(body)) or expired:
            raise InvalidShareToken("invalid or expired link")
        prefix = recap_prefix(user_id, week)
        record = await self._read(prefix)
        if record is None or not record.get("share_nonce"):
            raise InvalidShareToken("this link was turned off")
        if not hmac.compare_digest(str(record["share_nonce"]), nonce):
            raise InvalidShareToken("this link was turned off")
        return await self._render(record, prefix)


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


__all__ = ["InvalidShareToken", "RecapNotFound", "RecapService", "iso_week", "learner_hold"]
