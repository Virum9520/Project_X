from typing import Literal

from pydantic import Field

from sg_api.garden.schemas import Wire


class RecapSegmentOut(Wire):
    id: str
    kind: Literal["intro", "growth", "practice", "next", "outro"]
    text: str
    # Camera target in `focusToString` form: garden | grove:<id> | plant:<concept key>.
    focus: str
    concept_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    start_ms: int
    end_ms: int


class RecapOut(Wire):
    week: str
    week_start: str
    week_end: str
    generated_at: str
    narration: str
    segments: list[RecapSegmentOut]
    citations: list[str]
    duration_ms: int
    # aligned: word-accurate from TTS timestamps; proportional / estimated: approximate.
    timing: Literal["aligned", "proportional", "estimated"]
    quiet: bool
    rules_version: str
    audio_url: str | None = None  # None: text-only recap (no voice configured or budget spent)
    shared: bool = False


class GenerateRecapIn(Wire):
    force: bool = False


class ShareOut(Wire):
    token: str
    path: str
    expires_at: str
