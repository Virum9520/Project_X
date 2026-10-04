"""Demo seed CLI. Local and dev databases only.

uv run python -m sg_core.demo seed [--clerk-user-id user_xxx] [--email e] [--allow-dev]
uv run python -m sg_core.demo describe
"""

import argparse
import asyncio
import sys

from sg_core.demo.script import CONVOS, SCRIPT_VERSION
from sg_core.demo.seed import SeedRefusedError, seed_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sg_core.demo")
    commands = parser.add_subparsers(dest="command", required=True)
    seed = commands.add_parser("seed", help="create the demo learner and replay the history")
    seed.add_argument(
        "--clerk-user-id",
        help="Clerk user id of the account that will sign in as the demo learner "
        "(without it the seeded user cannot log in)",
    )
    seed.add_argument("--email", help="email of that account (add it to DEMO_ACCOUNT_EMAILS)")
    seed.add_argument(
        "--allow-dev", action="store_true", help="allow ENVIRONMENT=dev (shared dev database)"
    )
    commands.add_parser("describe", help="print the scripted history without touching a database")
    args = parser.parse_args(argv)

    if args.command == "describe":
        print(f"{SCRIPT_VERSION}: {len(CONVOS)} conversations")
        for c in sorted(CONVOS, key=lambda c: -c.days_ago):
            dims = ", ".join(f"{v.concept}/{v.dimension}:{v.outcome}" for v in c.verdicts)
            print(f"  -{c.days_ago:>2}d {c.mode:<12} {dims}")
        return 0

    try:
        report, clerk_id = asyncio.run(
            seed_database(
                clerk_user_id=args.clerk_user_id, email=args.email, allow_dev=args.allow_dev
            )
        )
    except SeedRefusedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("\n".join(report.lines()))
    print(f"demo learner clerk_user_id={clerk_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
