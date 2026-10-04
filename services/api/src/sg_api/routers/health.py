"""Liveness and readiness probes."""

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from sg_core.db import ping
from sg_core.logging import get_logger
from sg_core.settings import get_settings

router = APIRouter(tags=["health"])
log = get_logger(__name__)


class Health(BaseModel):
    status: str
    service: str
    environment: str


class Readiness(BaseModel):
    status: str
    checks: dict[str, bool]


@router.get("/healthz", response_model=Health)
async def healthz() -> Health:
    settings = get_settings()
    return Health(status="ok", service=settings.service_name, environment=settings.environment)


@router.get("/readyz", response_model=Readiness)
async def readyz(response: Response) -> Readiness:
    checks: dict[str, bool] = {}
    try:
        checks["database"] = await ping()
    except Exception as exc:  # readiness must report, not raise
        log.warning("readiness.database_failed", error=str(exc))
        checks["database"] = False
    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readiness(status="ready" if ready else "degraded", checks=checks)
