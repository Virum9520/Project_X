"""`sg-agents`: build, sync and voice-design commands for ElevenLabs agents-as-code.

uv run sg-agents build [--env dev] [--check] [--strict]
uv run sg-agents sync [--env dev] [--dry-run]
uv run sg-agents voices design <key>|--all
uv run sg-agents voices create <key> --preview N
uv run sg-agents ids
uv run sg-agents schema refresh <spec.json>
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from sg_agentops import compiler, schema, voices
from sg_core.settings import get_settings


def repo_root() -> Path:
    for parent in [Path.cwd(), *Path.cwd().parents]:
        if (parent / "agents" / "voices.yaml").exists():
            return parent
    sys.exit("error: run inside the Skill Garden repo (agents/voices.yaml not found)")


def agents_dir() -> Path:
    return repo_root() / "agents"


def _report(result: compiler.BuildResult, strict: bool) -> bool:
    for err in result.errors:
        print(f"error: {err}", file=sys.stderr)
    for item in result.unresolved:
        print(f"{'error' if strict else 'pending'}: {item}", file=sys.stderr)
    return not result.errors and not (strict and result.unresolved)


def cmd_build(args: argparse.Namespace) -> int:
    root = agents_dir()
    result = compiler.build(root, args.env)
    ok = _report(result, args.strict)
    if args.check:
        drift = result.drift(root)
        for path in drift:
            print(
                f"drift: agents/{path} is out of date; run `uv run sg-agents build`",
                file=sys.stderr,
            )
        return 0 if ok and not drift else 1
    if not ok:
        return 1
    changed = result.write(root)
    print(f"built {len(result.files)} files, {len(changed)} changed")
    return 0


def _elevenlabs(root: Path, *argv: str) -> None:
    exe = shutil.which("elevenlabs") or str(repo_root() / "node_modules" / ".bin" / "elevenlabs")
    key = get_settings().elevenlabs_api_key
    if key is None:
        sys.exit("error: ELEVENLABS_API_KEY is not set (root .env)")
    env = os.environ | {"ELEVENLABS_API_KEY": key.get_secret_value()}
    print(f"$ elevenlabs {' '.join(argv)}")
    subprocess.run([exe, *argv], cwd=root, env=env, check=True)


def cmd_sync(args: argparse.Namespace) -> int:
    """Push tools, then tests, then agents, rebuilding in between so IDs resolve."""
    root = agents_dir()
    dry = ["--dry-run"] if args.dry_run else []
    if args.update_only:
        new = compiler.unregistered(root)
        if new:
            sys.exit(f"error: would create new remote resources (push locally and commit): {new}")

    def rebuild(strict: bool) -> None:
        result = compiler.build(root, args.env)
        if not _report(result, strict):
            sys.exit(1)
        result.write(root)

    rebuild(strict=False)
    _elevenlabs(root, "tools", "push", *dry)
    rebuild(strict=False)
    _elevenlabs(root, "tests", "push", *dry)
    if not args.dry_run:
        rebuild(strict=not args.allow_unresolved)
    _elevenlabs(root, "agents", "push", *dry)
    print("synced. Set ELEVENLABS_AGENT_IDS from `uv run sg-agents ids`.")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    """Run each pushed agent's attached ElevenLabs tests; non-zero if any fail."""
    root = agents_dir()
    ids = compiler.agent_ids(root)
    selected = args.characters or sorted(ids)
    missing = [c for c in selected if c not in ids]
    if missing:
        sys.exit(f"error: not pushed yet: {missing} (run `uv run sg-agents sync`)")
    failed = []
    for character in selected:
        try:
            _elevenlabs(root, "agents", "test", ids[character])
        except subprocess.CalledProcessError:
            failed.append(character)
    if failed:
        print(f"failed: {', '.join(failed)}", file=sys.stderr)
    return 1 if failed else 0


def cmd_ids(_: argparse.Namespace) -> int:
    print(json.dumps(compiler.agent_ids(agents_dir()), sort_keys=True))
    return 0


def cmd_voices_design(args: argparse.Namespace) -> int:
    keys = None if args.all else [args.key]
    asyncio.run(voices.design(agents_dir(), keys))
    return 0


def cmd_voices_create(args: argparse.Namespace) -> int:
    asyncio.run(voices.create(agents_dir(), args.key, args.preview))
    return 0


def cmd_schema_refresh(args: argparse.Namespace) -> int:
    spec = json.loads(Path(args.spec).read_text())
    vendored = schema.vendor_schema(spec)
    schema.SCHEMA_PATH.write_text(json.dumps(vendored, indent=1, sort_keys=True) + "\n")
    print(f"vendored {len(vendored['components']['schemas'])} schemas")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sg-agents", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("build", help="compile agents/ sources into CLI configs")
    p.add_argument("--env", help="environment from agents/environments.yaml (default: its default)")
    p.add_argument("--check", action="store_true", help="fail if generated files are stale")
    p.add_argument("--strict", action="store_true", help="fail on unresolved voice/tool/test ids")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("sync", help="build and push tools, tests and agents to ElevenLabs")
    p.add_argument("--env")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--allow-unresolved", action="store_true", help="push even without voice ids")
    p.add_argument(
        "--update-only",
        action="store_true",
        help="refuse to create resources (for CI, which cannot commit the new IDs back)",
    )
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("test", help="run attached ElevenLabs agent tests")
    p.add_argument("characters", nargs="*", help="default: every pushed agent")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("ids", help="print character -> agent id JSON for ELEVENLABS_AGENT_IDS")
    p.set_defaults(func=cmd_ids)

    voices_parser = sub.add_parser("voices", help="Voice Design").add_subparsers(required=True)
    p = voices_parser.add_parser("design", help="generate previews for a character's voice")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("key", nargs="?")
    group.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_voices_design)
    p = voices_parser.add_parser("create", help="save a preview as the character's voice")
    p.add_argument("key")
    p.add_argument("--preview", type=int, required=True, help="preview number from `design`")
    p.set_defaults(func=cmd_voices_create)

    schema_parser = sub.add_parser("schema", help="vendored API schema").add_subparsers(
        required=True
    )
    p = schema_parser.add_parser(
        "refresh", help="re-vendor from `elevenlabs ... --spec-raw` output"
    )
    p.add_argument("spec")
    p.set_defaults(func=cmd_schema_refresh)

    args = parser.parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
