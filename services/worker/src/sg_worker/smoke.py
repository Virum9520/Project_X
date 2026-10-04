"""End-to-end worker check: enqueue `system.ping` through Hatchet and wait for the reply.

Proves the deployed worker is connected to Hatchet Cloud and executing tasks. Run it from any
machine with the same HATCHET_CLIENT_TOKEN as the worker:

    uv run --package sg_worker python -m sg_worker.smoke
"""

import sys
import time
import uuid

from sg_worker.tasks import PingInput, ping


def main() -> int:
    nonce = uuid.uuid4().hex[:8]
    started = time.perf_counter()
    result = ping.run(PingInput(message=nonce))
    elapsed = time.perf_counter() - started
    if result.message != f"pong: {nonce}":
        print(f"FAIL worker replied {result.message!r}", file=sys.stderr)
        return 1
    print(f"OK   worker round-trip in {elapsed:.1f}s ({result.message})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
