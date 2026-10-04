"""Generate the soundscape assets with ElevenLabs Music and Sound Effects (owner CLI backend).

Every provider call runs inside a developer-budget hold; an asset that already exists in the
`ObjectStore` for this version is skipped, so a re-run after a failure only pays for what is
missing. A manifest (`audio/v<N>/manifest.json`) lists what exists, and `audio/latest.json` points
the browser at the current version. Nothing here talks to a database directly: the budget hold is
injected (`HoldFactory`), defaulting to `sg_core.economics.budget_hold`.
"""

import hashlib
import json
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from sg_core.economics.budget import (
    BudgetExceededError,
    budget_hold,
    budget_key_for,
    monthly_limit_usd,
)
from sg_core.economics.usage import UsageContext
from sg_core.logging import get_logger
from sg_core.models.enums import CostCenter
from sg_core.providers.elevenlabs import AudioResult
from sg_core.providers.storage import ObjectNotFoundError, ObjectStore
from sg_core.soundscape.catalog import (
    ASSET_VERSION,
    LATEST_POINTER_KEY,
    MUSIC_LENGTH_MS,
    AssetSpec,
    manifest_key,
)

log = get_logger(__name__)

MANIFEST_SCHEMA = 1


class AudioClient(Protocol):
    async def compose_music(
        self, prompt: str, *, length_ms: int, model_id: str = ..., usage: UsageContext | None = ...
    ) -> AudioResult: ...
    async def generate_sound_effect(
        self,
        text: str,
        *,
        duration_seconds: float | None = ...,
        prompt_influence: float | None = ...,
        loop: bool = ...,
        usage: UsageContext | None = ...,
    ) -> AudioResult: ...


class HoldLike(Protocol):
    actual_usd: Decimal | None


# (amount_usd) -> async context manager; raises BudgetExceededError when the cap would be passed.
HoldFactory = Callable[[Decimal], AbstractAsyncContextManager[HoldLike]]


def developer_hold(amount_usd: Decimal) -> AbstractAsyncContextManager[Any]:
    """The real hold: reserve against `developer:YYYY-MM`, settle on success, release on error."""
    return budget_hold(
        budget_key=budget_key_for(CostCenter.DEVELOPER),
        amount_usd=amount_usd,
        limit_usd=monthly_limit_usd(CostCenter.DEVELOPER),
        cost_center=CostCenter.DEVELOPER,
    )


@dataclass(slots=True)
class GenerationReport:
    version: int
    generated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    estimated_usd: Decimal = Decimal(0)
    stopped_for_budget: bool = False

    @property
    def ok(self) -> bool:
        return not self.failed and not self.stopped_for_budget


def plan(
    specs: Sequence[AssetSpec], existing: set[str], version: int, *, force: bool
) -> list[AssetSpec]:
    return [s for s in specs if force or s.key(version) not in existing]


async def generate_assets(
    client: AudioClient,
    store: ObjectStore,
    specs: Sequence[AssetSpec],
    *,
    version: int = ASSET_VERSION,
    hold: HoldFactory = developer_hold,
    force: bool = False,
    dry_run: bool = False,
    max_usd: Decimal | None = None,
    publish_latest: bool = True,
) -> GenerationReport:
    report = GenerationReport(version=version)
    existing = set(await store.list_keys(f"audio/v{version}/"))
    todo = plan(specs, existing, version, force=force)
    report.skipped = [s.id for s in specs if s not in todo]
    report.estimated_usd = sum((s.estimate_usd() for s in todo), Decimal(0))
    if dry_run:
        report.generated = [s.id for s in todo]
        return report
    if max_usd is not None and report.estimated_usd > max_usd:
        raise ValueError(
            f"estimated ${report.estimated_usd} exceeds --max-usd {max_usd}; nothing generated"
        )

    for spec in todo:
        key = spec.key(version)
        try:
            async with hold(spec.estimate_usd()) as h:
                result = await _compose(client, spec, version)
                await store.put(key, result.audio, content_type=result.media_type)
                h.actual_usd = spec.estimate_usd()
        except BudgetExceededError:
            log.warning("soundscape.budget_exceeded", asset=spec.id)
            report.stopped_for_budget = True
            break
        except Exception as exc:  # one bad asset must not strand the rest
            log.warning("soundscape.asset_failed", asset=spec.id, exc_info=True)
            report.failed[spec.id] = f"{type(exc).__name__}: {exc}"
            continue
        report.generated.append(spec.id)

    await write_manifest(store, specs, version=version, publish_latest=publish_latest)
    return report


async def _compose(client: AudioClient, spec: AssetSpec, version: int) -> AudioResult:
    usage = UsageContext(
        cost_center=CostCenter.DEVELOPER,
        component="soundscape_assets",
        idempotency_key=f"soundscape:v{version}:{spec.id}",
    )
    if spec.kind == "music":
        return await client.compose_music(
            spec.prompt, length_ms=int(spec.duration_seconds * 1000) or MUSIC_LENGTH_MS, usage=usage
        )
    return await client.generate_sound_effect(
        spec.prompt, duration_seconds=spec.duration_seconds, loop=spec.loop, usage=usage
    )


async def write_manifest(
    store: ObjectStore,
    specs: Sequence[AssetSpec],
    *,
    version: int = ASSET_VERSION,
    publish_latest: bool = True,
) -> dict[str, Any]:
    """List the assets that exist for `version`. Safe to re-run; only reads and writes JSON."""
    assets: list[dict[str, Any]] = []
    for spec in specs:
        key = spec.key(version)
        try:
            stored = await store.get(key)
        except ObjectNotFoundError:
            continue
        assets.append(
            {
                "id": spec.id,
                "kind": spec.kind,
                "key": key,
                "mood": spec.mood,
                "season": spec.season,
                "loop": spec.loop,
                "duration_seconds": spec.duration_seconds,
                "content_type": stored.content_type or "audio/mpeg",
                "bytes": len(stored.data),
                "sha256": hashlib.sha256(stored.data).hexdigest(),
            }
        )
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "version": version,
        "generated_at": datetime.now(UTC).isoformat(),
        "assets": assets,
    }
    await store.put(
        manifest_key(version),
        json.dumps(manifest, indent=2).encode(),
        content_type="application/json",
    )
    if publish_latest and assets:
        await store.put(
            LATEST_POINTER_KEY,
            json.dumps({"version": version, "manifest_key": manifest_key(version)}).encode(),
            content_type="application/json",
        )
    return manifest


async def load_manifest(store: ObjectStore) -> dict[str, Any] | None:
    """The current manifest, or None when nothing has been generated yet."""
    try:
        pointer = json.loads((await store.get(LATEST_POINTER_KEY)).data)
        loaded: dict[str, Any] = json.loads((await store.get(pointer["manifest_key"])).data)
    except (ObjectNotFoundError, ValueError, KeyError):
        return None
    return loaded
