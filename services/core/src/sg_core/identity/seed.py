"""`python -m sg_core.identity.seed`: idempotently seed `capabilities` and `role_capabilities`."""

import asyncio

from sg_core.db import get_engine, get_sessionmaker
from sg_core.identity.db import seed_identity_catalog_committed


async def main() -> None:
    await seed_identity_catalog_committed(get_sessionmaker())
    await get_engine().dispose()
    print("identity catalogue seeded")


if __name__ == "__main__":
    asyncio.run(main())
