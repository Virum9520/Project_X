"""Curriculum CLI.

uv run python -m sg_core.curriculum validate [cs-core v1]
uv run python -m sg_core.curriculum load [cs-core v1] [--activate]
"""

import argparse
import asyncio
import sys

from sg_core.curriculum.loader import CurriculumError, curriculum_path, load_curriculum
from sg_core.curriculum.schema import CurriculumSpec
from sg_core.curriculum.sync import SyncResult, edge_rows, rubric_rows, sync_curriculum
from sg_core.db import get_engine, get_sessionmaker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sg_core.curriculum")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("validate", "validate the YAML and print a summary"),
        ("load", "validate, then sync into DATABASE_URL"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("key", nargs="?", default="cs-core")
        command.add_argument("version", nargs="?", default="v1")
    commands.choices["load"].add_argument(
        "--activate", action="store_true", help="make this the active version of its key"
    )
    args = parser.parse_args(argv)

    try:
        spec = load_curriculum(curriculum_path(args.key, args.version))
    except CurriculumError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_summary(spec)

    if args.command == "load":
        try:
            result = asyncio.run(_load(spec, activate=args.activate))
        except CurriculumError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"{result.action}: {spec.ref} is {result.status.value} (id {result.curriculum_id})")
    return 0


async def _load(spec: CurriculumSpec, *, activate: bool) -> SyncResult:
    try:
        async with get_sessionmaker()() as session, session.begin():
            return await sync_curriculum(session, spec, activate=activate)
    finally:
        await get_engine().dispose()


def _print_summary(spec: CurriculumSpec) -> None:
    edges = edge_rows(spec)
    prerequisites = sum(1 for *_, kind in edges if kind == "prerequisite")
    print(f"{spec.ref}  {spec.title}")
    for domain in spec.domains:
        print(f"  {domain.key:<14} {len(spec.concepts_in(domain.key)):>3} concepts")
    print(
        f"  {len(spec.concepts)} concepts, {prerequisites} prerequisite and "
        f"{len(edges) - prerequisites} related edges, {len(rubric_rows(spec))} rubrics "
        f"(v{spec.rubric_version})"
    )
    print(f"  content hash {spec.content_hash}")


if __name__ == "__main__":
    raise SystemExit(main())
