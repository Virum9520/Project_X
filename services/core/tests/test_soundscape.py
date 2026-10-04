import json
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest

from sg_core.economics.budget import BudgetExceededError
from sg_core.economics.usage import UsageContext
from sg_core.providers.elevenlabs import AudioResult
from sg_core.providers.storage import InMemoryObjectStore
from sg_core.soundscape import (
    MOODS,
    SEASONS,
    SFX_NAMES,
    all_specs,
    generate_assets,
    load_manifest,
)
from sg_core.soundscape.__main__ import main, select
from sg_core.soundscape.catalog import LATEST_POINTER_KEY, manifest_key


class FakeClient:
    def __init__(self, fail_ids: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str, UsageContext | None]] = []
        self.fail = fail_ids or set()

    async def compose_music(
        self, prompt: str, *, length_ms: int, model_id: str = "x", usage: UsageContext | None = None
    ) -> AudioResult:
        assert length_ms == 30_000
        return self._ok("music", prompt, usage)

    async def generate_sound_effect(
        self,
        text: str,
        *,
        duration_seconds: float | None = None,
        prompt_influence: float | None = None,
        loop: bool = False,
        usage: UsageContext | None = None,
    ) -> AudioResult:
        assert duration_seconds is not None
        return self._ok("sfx", text, usage)

    def _ok(self, kind: str, prompt: str, usage: UsageContext | None) -> AudioResult:
        assert usage is not None and usage.idempotency_key
        self.calls.append((kind, prompt, usage))
        if usage.idempotency_key.rsplit(":", 1)[1] in self.fail:
            raise RuntimeError("provider down")
        return AudioResult(audio=f"audio:{usage.idempotency_key}".encode())


class Holds:
    def __init__(self, cap: int | None = None) -> None:
        self.amounts: list[Decimal] = []
        self.settled: list[Decimal | None] = []
        self.cap = cap

    @asynccontextmanager
    async def __call__(self, amount: Decimal):  # type: ignore[no-untyped-def]
        if self.cap is not None and len(self.amounts) >= self.cap:
            raise BudgetExceededError("developer:test", Decimal(1), Decimal(1), amount)
        self.amounts.append(amount)

        class H:
            actual_usd: Decimal | None = None

        h = H()
        yield h
        self.settled.append(h.actual_usd)


def test_catalogue_covers_moods_seasons_and_sfx() -> None:
    specs = all_specs()
    ids = {s.id for s in specs}
    assert len(ids) == len(specs) == len(MOODS) * len(SEASONS) + len(SFX_NAMES)
    assert "music.wilting.autumn" in ids and "sfx.bloom" in ids
    assert all(s.loop for s in specs if s.kind == "music")
    assert all(s.estimate_usd() > 0 for s in specs)
    assert all(s.key(2).startswith("audio/v2/") and s.key().endswith(".mp3") for s in specs)


async def test_generates_everything_with_holds_and_manifest() -> None:
    store, client, holds = InMemoryObjectStore(), FakeClient(), Holds()
    report = await generate_assets(client, store, all_specs(), hold=holds)  # type: ignore[arg-type]
    assert report.ok and len(report.generated) == len(all_specs())
    assert len(holds.amounts) == len(all_specs())
    assert all(a is not None and a > 0 for a in holds.settled) or holds.settled == []
    manifest = await load_manifest(store)
    assert manifest is not None and len(manifest["assets"]) == len(all_specs())
    first = manifest["assets"][0]
    assert first["sha256"] and first["bytes"] > 0
    pointer = json.loads((await store.get(LATEST_POINTER_KEY)).data)
    assert pointer["manifest_key"] == manifest_key(1)
    assert all(c[2].cost_center.value == "developer" for c in client.calls)  # type: ignore[union-attr]


async def test_rerun_skips_existing_and_only_pays_for_missing() -> None:
    store, holds = InMemoryObjectStore(), Holds()
    specs = select(all_specs(), ["sfx.*"])
    await generate_assets(FakeClient(), store, specs, hold=holds)  # type: ignore[arg-type]
    holds2, client2 = Holds(), FakeClient()
    report = await generate_assets(client2, store, all_specs(), hold=holds2)  # type: ignore[arg-type]
    assert len(report.skipped) == len(specs)
    assert len(client2.calls) == len(all_specs()) - len(specs) == len(holds2.amounts)
    forced = await generate_assets(FakeClient(), store, specs, hold=Holds(), force=True)  # type: ignore[arg-type]
    assert forced.skipped == [] and len(forced.generated) == len(specs)


async def test_failure_is_reported_and_others_continue() -> None:
    store = InMemoryObjectStore()
    report = await generate_assets(
        FakeClient({"sfx.wilt"}),
        store,
        select(all_specs(), ["sfx.*"]),
        hold=Holds(),  # type: ignore[arg-type]
    )
    assert not report.ok and list(report.failed) == ["sfx.wilt"]
    assert len(report.generated) == len(SFX_NAMES) - 1
    manifest = await load_manifest(store)
    assert manifest and "sfx.wilt" not in {a["id"] for a in manifest["assets"]}


async def test_budget_exhaustion_stops_and_keeps_what_was_made() -> None:
    store = InMemoryObjectStore()
    report = await generate_assets(
        FakeClient(),
        store,
        select(all_specs(), ["sfx.*"]),
        hold=Holds(cap=3),  # type: ignore[arg-type]
    )
    assert report.stopped_for_budget and len(report.generated) == 3 and not report.ok
    manifest = await load_manifest(store)
    assert manifest and len(manifest["assets"]) == 3


async def test_dry_run_and_max_usd_make_no_calls() -> None:
    store, client = InMemoryObjectStore(), FakeClient()
    dry = await generate_assets(client, store, all_specs(), hold=Holds(), dry_run=True)  # type: ignore[arg-type]
    assert dry.estimated_usd > 0 and not client.calls and await store.list_keys() == []
    with pytest.raises(ValueError, match="max-usd"):
        await generate_assets(
            client,
            store,
            all_specs(),
            hold=Holds(),
            max_usd=Decimal("0.01"),  # type: ignore[arg-type]
        )
    assert not client.calls


async def test_manifest_missing_returns_none() -> None:
    assert await load_manifest(InMemoryObjectStore()) is None


def test_cli_plan_and_selection(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["plan", "--only", "sfx.*"]) == 0
    out = capsys.readouterr().out
    assert "sfx.growth" in out and "music." not in out
    assert main(["plan", "--only", "nothing.*"]) == 1
