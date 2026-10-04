"""Price book and cost estimation.

Prices live in `pricing_versions` (effective-dated, never edited in place). `DEFAULT_PRICES` seeds
the table (`sync_default_prices`) and is the fallback when the table has no row, so cost
estimates work before any owner edits. These are planning estimates: provider-reported cost
(OpenRouter) and reconciled cost (ElevenLabs conversation metadata) always supersede them.

SKU conventions (unit in brackets):
- `elevenlabs`: `agent_minute` [minute], `tts_character` [character], `sound_generation_second`
  [second], `music_second` [second], `speech_to_text_second` [second], `voice_design` [request]
- `openrouter` / `openai`: `<model>:input|output|cache_read|cache_write|reasoning` [token]
- `e2b`: `sandbox_second` [second]
A SKU with no price yields no estimate (cost stays unknown) instead of a silent zero.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sg_core.models.economics import PricingVersion

PRICE_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
MICRO = Decimal("0.000001")


@dataclass(frozen=True, slots=True)
class PriceEntry:
    provider: str
    sku: str
    unit: str
    unit_price: Decimal
    effective_from: datetime = PRICE_EPOCH
    effective_to: datetime | None = None
    id: UUID | None = None
    source_url: str | None = None

    def active_at(self, at: datetime) -> bool:
        return self.effective_from <= at and (self.effective_to is None or at < self.effective_to)


def _p(provider: str, sku: str, unit: str, price: str, url: str | None = None) -> PriceEntry:
    return PriceEntry(provider, sku, unit, Decimal(price), source_url=url)


_EL = "https://elevenlabs.io/pricing/api"
_OR = "https://openrouter.ai/models"
_OA = "https://platform.openai.com/docs/pricing"

# Estimates. Confirm against the vendor price pages before relying on them for owner reporting.
DEFAULT_PRICES: tuple[PriceEntry, ...] = (
    _p("elevenlabs", "agent_minute", "minute", "0.10", _EL),
    _p("elevenlabs", "tts_character", "character", "0.00005", _EL),
    _p("elevenlabs", "sound_generation_second", "second", "0.002", _EL),
    _p("elevenlabs", "music_second", "second", "0.005", _EL),
    _p("elevenlabs", "speech_to_text_second", "second", "0.0001", _EL),
    _p("elevenlabs", "voice_design", "request", "0.05", _EL),
    _p("openai", "text-embedding-3-small:input", "token", "0.00000002", _OA),
    _p("openai", "text-embedding-3-large:input", "token", "0.00000013", _OA),
    _p("openrouter", "anthropic/claude-sonnet-4.5:input", "token", "0.000003", _OR),
    _p("openrouter", "anthropic/claude-sonnet-4.5:output", "token", "0.000015", _OR),
    _p("openrouter", "anthropic/claude-sonnet-4.5:cache_read", "token", "0.0000003", _OR),
    _p("openrouter", "anthropic/claude-sonnet-4.5:cache_write", "token", "0.00000375", _OR),
    _p("openrouter", "openai/gpt-4o-mini:input", "token", "0.00000015", _OR),
    _p("openrouter", "openai/gpt-4o-mini:output", "token", "0.0000006", _OR),
    _p("e2b", "sandbox_second", "second", "0.000014", "https://e2b.dev/pricing"),
)


@dataclass(frozen=True, slots=True)
class LineItem:
    sku: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    pricing_version_id: UUID | None

    @property
    def usd(self) -> Decimal:
        return self.quantity * self.unit_price


@dataclass(frozen=True, slots=True)
class CostEstimate:
    usd: Decimal
    native_amount: Decimal
    native_unit: str
    items: tuple[LineItem, ...]

    @property
    def pricing_version_id(self) -> UUID | None:
        """The row the entry points at: the first (usually only) priced line item."""
        return self.items[0].pricing_version_id if self.items else None


class PriceBook:
    """Effective-dated lookup. DB rows win over defaults for the same (provider, sku)."""

    def __init__(self, entries: Iterable[PriceEntry] = DEFAULT_PRICES) -> None:
        self._entries: dict[tuple[str, str], list[PriceEntry]] = {}
        for entry in entries:
            self._entries.setdefault((entry.provider, entry.sku), []).append(entry)

    @classmethod
    async def load(cls, session: AsyncSession) -> "PriceBook":
        rows = (await session.scalars(select(PricingVersion))).all()
        db = [
            PriceEntry(
                provider=r.provider,
                sku=r.sku,
                unit=r.unit,
                unit_price=r.unit_price,
                effective_from=r.effective_from,
                effective_to=r.effective_to,
                id=r.id,
                source_url=r.source_url,
            )
            for r in rows
        ]
        covered = {(e.provider, e.sku) for e in db}
        return cls([*db, *(d for d in DEFAULT_PRICES if (d.provider, d.sku) not in covered)])

    def price(self, provider: str, sku: str, at: datetime | None = None) -> PriceEntry | None:
        at = at or datetime.now(UTC)
        candidates = [e for e in self._entries.get((provider, sku), []) if e.active_at(at)]
        return max(candidates, key=lambda e: e.effective_from, default=None)

    def estimate(
        self,
        provider: str,
        quantities: Sequence[tuple[str, Decimal | int | float | None]],
        at: datetime | None = None,
    ) -> CostEstimate | None:
        """Price `(sku, quantity)` pairs. Skips None/zero quantities; None if nothing priced.

        If any requested non-zero quantity has no price the whole estimate is None: a partial
        sum would understate cost.
        """
        items: list[LineItem] = []
        for sku, quantity in quantities:
            if quantity is None or Decimal(str(quantity)) == 0:
                continue
            entry = self.price(provider, sku, at)
            if entry is None:
                return None
            items.append(
                LineItem(sku, Decimal(str(quantity)), entry.unit, entry.unit_price, entry.id)
            )
        if not items:
            return None
        usd = sum((i.usd for i in items), Decimal(0)).quantize(MICRO)
        if len(items) == 1:
            native, unit = items[0].quantity, items[0].unit
        else:
            native, unit = usd, "usd"
        return CostEstimate(usd=usd, native_amount=native, native_unit=unit, items=tuple(items))


async def sync_default_prices(session: AsyncSession) -> int:
    """Insert any default price row missing from `pricing_versions`. Returns rows added."""
    existing = {
        (r.provider, r.sku, r.effective_from)
        for r in (await session.scalars(select(PricingVersion))).all()
    }
    added = 0
    for e in DEFAULT_PRICES:
        if (e.provider, e.sku, e.effective_from) in existing:
            continue
        session.add(
            PricingVersion(
                provider=e.provider,
                sku=e.sku,
                unit=e.unit,
                unit_price=e.unit_price,
                effective_from=e.effective_from,
                source_url=e.source_url,
            )
        )
        added += 1
    await session.flush()
    return added
