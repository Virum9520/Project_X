"""Liveness and readiness probes.

`/healthz` is liveness only (no dependencies). `/readyz` checks backing services and is the
Railway deploy health check, so a misconfigured release never takes traffic.
"""

import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from sg_core import db, redis_client
from sg_core.logging import get_logger
from sg_core.settings import get_settings

router = APIRouter(tags=["health"])
log = get_logger(__name__)

CHECK_TIMEOUT_SECONDS = 5.0


class Health(BaseModel):
    status: str
    service: str
    environment: str
    commit: str | None = None


class Readiness(BaseModel):
    status: str
    checks: dict[str, bool]


@router.get("/healthz", response_model=Health)
async def healthz() -> Health:
    settings = get_settings()
    return Health(
        status="ok",
        service=settings.service_name,
        environment=settings.environment,
        commit=settings.git_sha,
    )


@router.get("/readyz", response_model=Readiness)
async def readyz(response: Response) -> Readiness:
    probes: dict[str, Callable[[], Awaitable[bool]]] = {"database": db.ping}
    if get_settings().redis_url:
        probes["redis"] = redis_client.ping

    results = await asyncio.gather(*(_run_check(name, probe) for name, probe in probes.items()))
    checks = dict(zip(probes, results, strict=True))
    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readiness(status="ready" if ready else "degraded", checks=checks)


async def _run_check(name: str, probe: Callable[[], Awaitable[bool]]) -> bool:
    try:
        return await asyncio.wait_for(probe(), timeout=CHECK_TIMEOUT_SECONDS)
    except Exception as exc:  # readiness must report, not raise
        log.warning("readiness.check_failed", check=name, error=repr(exc))
        return False
