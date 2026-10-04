"""Owner CLI: generate the soundscape assets (needs ELEVENLABS_API_KEY and S3_* credentials).

uv run python -m sg_core.soundscape plan                      # list assets and estimated cost
uv run python -m sg_core.soundscape generate [--version N] [--only music.seedling.*]
                                              [--force] [--dry-run] [--max-usd 2.50]
uv run python -m sg_core.soundscape manifest                  # rebuild the manifest from the store

Each asset runs inside a developer-budget hold. Re-running skips what already exists.
"""

import argparse
import asyncio
import fnmatch
import sys
from decimal import Decimal

from sg_core.providers.elevenlabs import client_from_settings
from sg_core.providers.storage import object_store_from_settings
from sg_core.soundscape.catalog import ASSET_VERSION, AssetSpec, all_specs
from sg_core.soundscape.generate import generate_assets, write_manifest


def select(specs: list[AssetSpec], patterns: list[str] | None) -> list[AssetSpec]:
    if not patterns:
        return specs
    return [s for s in specs if any(fnmatch.fnmatch(s.id, p) for p in patterns)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sg_core.soundscape")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "generate", "manifest"):
        c = commands.add_parser(name)
        c.add_argument("--version", type=int, default=ASSET_VERSION)
        c.add_argument("--only", action="append", help="glob on asset id, e.g. 'sfx.*'")
    commands.choices["generate"].add_argument("--force", action="store_true")
    commands.choices["generate"].add_argument("--dry-run", action="store_true")
    commands.choices["generate"].add_argument("--max-usd", type=Decimal)
    args = parser.parse_args(argv)

    specs = select(all_specs(), args.only)
    if not specs:
        print("error: --only matched no assets", file=sys.stderr)
        return 1
    if args.command == "plan":
        for s in specs:
            print(
                f"{s.id:32} {s.duration_seconds:5.1f}s  ~${s.estimate_usd()}  {s.key(args.version)}"
            )
        print(f"{len(specs)} assets, ~${sum((s.estimate_usd() for s in specs), Decimal(0))}")
        return 0
    try:
        return asyncio.run(_run(args, specs))
    except (RuntimeError, ValueError) as exc:  # not configured, estimate over --max-usd
        print(f"error: {exc}", file=sys.stderr)
        return 1


async def _run(args: argparse.Namespace, specs: list[AssetSpec]) -> int:
    store = object_store_from_settings()
    if args.command == "manifest":
        manifest = await write_manifest(store, specs, version=args.version)
        print(f"manifest v{args.version}: {len(manifest['assets'])} assets")
        return 0
    async with client_from_settings() as client:
        report = await generate_assets(
            client,
            store,
            specs,
            version=args.version,
            force=args.force,
            dry_run=args.dry_run,
            max_usd=args.max_usd,
        )
    verb = "would generate" if args.dry_run else "generated"
    print(
        f"{verb} {len(report.generated)}, skipped {len(report.skipped)}, ~${report.estimated_usd}"
    )
    for asset_id, why in report.failed.items():
        print(f"failed {asset_id}: {why}", file=sys.stderr)
    if report.stopped_for_budget:
        print(
            "stopped: developer budget exhausted; re-run next period or raise the cap",
            file=sys.stderr,
        )
    return 0 if report.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
