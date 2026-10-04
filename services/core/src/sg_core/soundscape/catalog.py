"""The soundscape asset catalogue: what the owner script generates and the browser engine plays.

Music is a loopable stem per garden mood and season; SFX covers growth, bloom, wilt, ring and UI.
Bump `ASSET_VERSION` to regenerate everything under a new prefix (old versions stay in the store,
so a rollback is a one-line pointer change). Ids are the contract with `@sg/audio`: the engine
looks stems up as `music.<mood>.<season>` and effects as `sfx.<name>`.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sg_core.economics.pricing import PriceBook

ASSET_VERSION = 1

MOODS = ("seedling", "thriving", "wilting", "blooming")
SEASONS = ("spring", "summer", "autumn", "winter")
SFX_NAMES = (
    "growth",
    "bloom",
    "wilt",
    "ring",
    "ui_click",
    "ui_open",
    "ui_close",
    "recap_start",
)

MUSIC_LENGTH_MS = 30_000

_MOOD_PROMPTS = {
    "seedling": "gentle, hopeful, sparse; soft felt piano and warm pads, a sense of beginnings",
    "thriving": "warm, steady and confident; acoustic guitar, light percussion and strings",
    "wilting": "quiet, wistful and slow; muted keys and low pads, a little unresolved",
    "blooming": "bright, joyful and expansive; harp, chimes and swelling strings, celebratory",
}
_SEASON_PROMPTS = {
    "spring": "fresh spring morning feel, birdsong-like high textures",
    "summer": "long sunlit summer afternoon, relaxed and open",
    "autumn": "golden autumn evening, mellow and reflective",
    "winter": "still winter night, crystalline and spacious",
}
_SFX_PROMPTS: dict[str, tuple[str, float]] = {
    "growth": ("soft magical sprout unfurling, gentle rising shimmer, no voices", 1.5),
    "bloom": ("a flower blossoming with a bright chime flourish, warm and brief, no voices", 2.0),
    "wilt": ("a soft downward sigh of a plant drooping, muted and gentle, no voices", 1.5),
    "ring": ("a calm, friendly phone ring tone, two soft chimes, polite and brief", 2.0),
    "ui_click": ("subtle soft interface tap, wooden, very short", 0.5),
    "ui_open": ("gentle airy whoosh with a soft chime, panel opening", 0.8),
    "ui_close": ("gentle airy whoosh downward, panel closing", 0.6),
    "recap_start": ("warm cinematic chime swell introducing a story, brief", 2.5),
}

MUSIC_SUFFIX = (
    " Seamless loop, instrumental only, no vocals, calm background music for a focused learning "
    "app, mixed quietly."
)


@dataclass(frozen=True, slots=True)
class AssetSpec:
    id: str
    kind: Literal["music", "sfx"]
    prompt: str
    duration_seconds: float
    loop: bool = False
    mood: str | None = None
    season: str | None = None

    @property
    def filename(self) -> str:
        return f"{self.id.replace('.', '/')}.mp3"

    def key(self, version: int = ASSET_VERSION) -> str:
        return f"{asset_prefix(version)}{self.filename}"

    def estimate_usd(self, prices: PriceBook | None = None) -> Decimal:
        book = prices or PriceBook()
        sku = "music_second" if self.kind == "music" else "sound_generation_second"
        est = book.estimate("elevenlabs", [(sku, Decimal(str(self.duration_seconds)))])
        # Unpriced means the price book has no row: hold a conservative flat amount, never zero.
        return est.usd if est else Decimal("0.25")


def asset_prefix(version: int = ASSET_VERSION) -> str:
    return f"audio/v{version}/"


def manifest_key(version: int = ASSET_VERSION) -> str:
    return f"{asset_prefix(version)}manifest.json"


LATEST_POINTER_KEY = "audio/latest.json"


def music_specs() -> list[AssetSpec]:
    return [
        AssetSpec(
            id=f"music.{mood}.{season}",
            kind="music",
            prompt=f"{_MOOD_PROMPTS[mood]}; {_SEASON_PROMPTS[season]}.{MUSIC_SUFFIX}",
            duration_seconds=MUSIC_LENGTH_MS / 1000,
            loop=True,
            mood=mood,
            season=season,
        )
        for mood in MOODS
        for season in SEASONS
    ]


def sfx_specs() -> list[AssetSpec]:
    return [
        AssetSpec(
            id=f"sfx.{name}",
            kind="sfx",
            prompt=_SFX_PROMPTS[name][0],
            duration_seconds=_SFX_PROMPTS[name][1],
        )
        for name in SFX_NAMES
    ]


def all_specs() -> list[AssetSpec]:
    return [*music_specs(), *sfx_specs()]
