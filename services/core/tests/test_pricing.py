from datetime import UTC, datetime
from decimal import Decimal

from sg_core.economics import PriceBook, UsageMeasure, estimate_measure
from sg_core.economics.pricing import PriceEntry


def test_agent_minutes_priced_from_connected_seconds() -> None:
    est = estimate_measure(
        UsageMeasure(provider="elevenlabs", connected_seconds=Decimal(90)), PriceBook()
    )
    assert est is not None
    assert est.usd == Decimal("0.150000")
    assert est.native_unit == "minute"


def test_cached_tokens_are_priced_at_cache_rate_not_twice() -> None:
    measure = UsageMeasure(
        provider="openrouter",
        model="anthropic/claude-sonnet-4.5",
        input_tokens=1000,
        output_tokens=100,
        cache_read_tokens=800,
    )
    est = estimate_measure(measure, PriceBook())
    assert est is not None
    # 200 fresh * 3e-6 + 100 out * 15e-6 + 800 cached * 3e-7
    assert est.usd == Decimal("0.002340")
    assert est.native_unit == "usd"


def test_unknown_model_is_unpriced_not_zero() -> None:
    measure = UsageMeasure(
        provider="openrouter", model="nobody/model", input_tokens=10, output_tokens=5
    )
    assert estimate_measure(measure, PriceBook()) is None


def test_unreported_tokens_are_not_priced_as_zero() -> None:
    measure = UsageMeasure(provider="openai", model="text-embedding-3-small", input_tokens=None)
    assert estimate_measure(measure, PriceBook()) is None


def test_price_is_effective_dated() -> None:
    old = PriceEntry(
        "e2b",
        "sandbox_second",
        "second",
        Decimal("1"),
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 6, 1, tzinfo=UTC),
    )
    new = PriceEntry(
        "e2b", "sandbox_second", "second", Decimal("2"), datetime(2026, 6, 1, tzinfo=UTC)
    )
    book = PriceBook([old, new])
    assert book.price("e2b", "sandbox_second", datetime(2026, 3, 1, tzinfo=UTC)) == old
    assert book.price("e2b", "sandbox_second", datetime(2026, 7, 1, tzinfo=UTC)) == new
    assert book.price("e2b", "sandbox_second", datetime(2025, 1, 1, tzinfo=UTC)) is None


def test_partial_pricing_returns_none() -> None:
    book = PriceBook([PriceEntry("p", "m:input", "token", Decimal("1"))])
    assert book.estimate("p", [("m:input", 5), ("m:output", 5)]) is None
