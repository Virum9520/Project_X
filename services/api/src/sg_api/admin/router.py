"""Owner-console data routes: `/v1/admin/*`.

Every route needs an admin session (owner allowlist or grant, verified email, second factor) plus
one specific capability, checked here and never in the browser. Mutations also pass the CSRF
origin guard and are audited by `AuditMiddleware`. Reads are not audited (they are logged by the
access log); the audit log records who changed or triggered something.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from sg_api.admin import call_now as call_now_service
from sg_api.admin.deps import DispatcherDep, SettingsDep, StoreDep
from sg_api.admin.schemas import (
    TEST_PROFILES,
    AgentRow,
    AuditPage,
    CalibrationSummary,
    CallNowOptions,
    CallNowRequest,
    CallNowResult,
    CallsReport,
    ComponentStatus,
    CostGroupBy,
    CostReport,
    Overview,
    QualityReport,
    SystemStatus,
    UserDetail,
    UserPage,
)
from sg_api.admin.util import mask_phone
from sg_api.auth import AdminPrincipal, admin_origin_guard, record_audit, require_capability
from sg_core.economics.budget import monthly_limit_usd
from sg_core.evidence.calibration import load_report
from sg_core.identity import Capability
from sg_core.logging import get_logger
from sg_core.models.enums import CostCenter
from sg_core.settings import Settings

log = get_logger(__name__)

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin-console"],
    dependencies=[Depends(admin_origin_guard)],
)


def _need(capability: Capability) -> Any:
    return Depends(require_capability(capability))


MAX_COST_RANGE_DAYS = 366


# ── Overview ──
@router.get("/overview", response_model=Overview, dependencies=[_need(Capability.USAGE_READ)])
async def overview(store: StoreDep) -> Overview:
    return await store.overview(datetime.now(UTC))


# ── Users ──
@router.get("/users", response_model=UserPage, dependencies=[_need(Capability.USERS_READ)])
async def list_users(
    store: StoreDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> UserPage:
    return await store.list_users(q, limit, offset)


@router.get(
    "/users/{user_id}", response_model=UserDetail, dependencies=[_need(Capability.USERS_READ)]
)
async def get_user(user_id: uuid.UUID, store: StoreDep) -> UserDetail:
    detail = await store.get_user(user_id, datetime.now(UTC))
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return detail


# ── Usage and costs ──
@router.get("/costs", response_model=CostReport, dependencies=[_need(Capability.USAGE_READ)])
async def costs(
    store: StoreDep,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    group_by: Annotated[CostGroupBy, Query()] = "component",
) -> CostReport:
    now = datetime.now(UTC)
    end = end or now.date()
    start = start or end.replace(day=1)
    if start > end:
        raise HTTPException(422, "start is after end")
    if (end - start) > timedelta(days=MAX_COST_RANGE_DAYS):
        raise HTTPException(422, "range is limited to one year")
    return await store.costs(start, end, group_by, now)


# ── Calls and agents ──
@router.get("/calls", response_model=CallsReport, dependencies=[_need(Capability.CALLS_READ)])
async def calls(store: StoreDep) -> CallsReport:
    return await store.calls(datetime.now(UTC))


@router.get("/agents", response_model=list[AgentRow], dependencies=[_need(Capability.CALLS_READ)])
async def agents(store: StoreDep, settings: SettingsDep) -> list[AgentRow]:
    return await store.agents(settings.elevenlabs_agent_ids, datetime.now(UTC))


@router.get(
    "/calls/now/options",
    response_model=CallNowOptions,
    dependencies=[_need(Capability.CALLS_READ)],
)
async def call_now_options(
    store: StoreDep, dispatcher: DispatcherDep, settings: SettingsDep
) -> CallNowOptions:
    now = datetime.now(UTC)
    per_minute = call_now_service.cost_per_minute()
    return CallNowOptions(
        agents=await store.agents(settings.elevenlabs_agent_ids, now),
        # The owner's own approved test destinations; the API re-checks them on submit.
        targets=list(settings.call_now_approved_targets),
        test_profiles=list(TEST_PROFILES),
        max_duration_seconds=settings.call_now_max_duration_seconds,
        min_duration_seconds=call_now_service.MIN_DURATION_SECONDS,
        cooldown_seconds=settings.call_now_cooldown_seconds,
        cost_per_minute_usd=float(per_minute) if per_minute is not None else None,
        developer_budget=await store.developer_budget(
            monthly_limit_usd(CostCenter.DEVELOPER, settings), now
        ),
        dispatcher=dispatcher.name,
    )


@router.post("/calls/now", response_model=CallNowResult)
async def call_now(
    request: Request,
    body: CallNowRequest,
    principal: Annotated[AdminPrincipal, _need(Capability.CALLS_TRIGGER)],
    store: StoreDep,
    dispatcher: DispatcherDep,
    settings: SettingsDep,
) -> CallNowResult:
    # Recorded up front so refused and failed attempts are audited with their parameters too.
    params = {
        "agent": body.agent,
        "agent_version": body.agent_version,
        "target": "web" if body.target == "web" else mask_phone(body.target),
        "test_profile": body.test_profile,
        "duration_seconds": body.duration_seconds,
        "request_id": body.request_id,
    }
    record_audit(
        request, action="calls.now", target=f"call_request:{body.request_id}", after=params
    )
    try:
        result = await call_now_service.call_now(
            store=store,
            dispatcher=dispatcher,
            settings=settings,
            body=body,
            requested_by=principal.user_id,
        )
    except call_now_service.CallNowError as exc:
        headers = {"Retry-After": str(exc.retry_after_s)} if exc.retry_after_s else None
        raise HTTPException(exc.status_code, exc.detail, headers=headers) from exc
    record_audit(
        request,
        action="calls.now.replay" if result.replayed else "calls.now",
        target=f"call:{result.occurrence_id}",
        after={**params, "state": result.state, "dispatcher": dispatcher.name},
    )
    return result


# ── Quality, operations, system ──
@router.get("/quality", response_model=QualityReport, dependencies=[_need(Capability.QUALITY_READ)])
async def quality(store: StoreDep) -> QualityReport:
    report = await store.quality(datetime.now(UTC))
    return report.model_copy(update={"calibration": _calibration_summary()})


def _calibration_summary() -> CalibrationSummary | None:
    """Latest saved calibration run (`python -m sg_core.evidence.calibration`), if any."""
    raw = load_report()
    if raw is None:
        return None
    try:
        return CalibrationSummary(
            **{k: raw[k] for k in CalibrationSummary.model_fields if k != "by_dimension"},
            by_dimension={d: v["disagreements"] for d, v in raw["by_dimension"].items()},
        )
    except (KeyError, TypeError, ValueError):
        log.warning("admin.calibration_report_unreadable")
        return None


@router.get("/system", response_model=SystemStatus, dependencies=[_need(Capability.QUALITY_READ)])
async def system(store: StoreDep, dispatcher: DispatcherDep, settings: SettingsDep) -> SystemStatus:
    components: list[ComponentStatus] = []
    try:
        await store.ping()
        components.append(ComponentStatus(name="database", ok=True))
    except Exception as exc:
        components.append(ComponentStatus(name="database", ok=False, detail=type(exc).__name__))
    components.append(await _redis_status(settings))
    components.append(
        ComponentStatus(
            name="call_dispatcher",
            ok=dispatcher.name != "stub",
            detail="stub: no calls are placed" if dispatcher.name == "stub" else dispatcher.name,
        )
    )
    return SystemStatus(
        generated_at=datetime.now(UTC),
        environment=settings.environment.value,
        git_sha=settings.git_sha,
        components=components,
        configured=_configured(settings),
    )


async def _redis_status(settings: Settings) -> ComponentStatus:
    if not settings.redis_url:
        return ComponentStatus(name="redis", ok=True, detail="not configured (optional)")
    from sg_core import redis_client

    try:
        await redis_client.ping()
        return ComponentStatus(name="redis", ok=True)
    except Exception as exc:
        return ComponentStatus(name="redis", ok=False, detail=type(exc).__name__)


def _configured(settings: Settings) -> dict[str, bool]:
    return {
        "clerk": bool(settings.clerk_issuer and settings.clerk_secret_key),
        "elevenlabs_api_key": settings.elevenlabs_api_key is not None,
        "elevenlabs_webhook_secret": settings.elevenlabs_webhook_secret is not None,
        "elevenlabs_agent_ids": bool(settings.elevenlabs_agent_ids),
        "openrouter": settings.openrouter_api_key is not None,
        "openai": settings.openai_api_key is not None,
        "e2b": settings.e2b_api_key is not None,
        "hatchet": settings.hatchet_client_token is not None,
        "redis": bool(settings.redis_url),
        "owner_allowlist": bool(settings.admin_owner_emails),
    }


# ── Audit log ──
@router.get("/audit", response_model=AuditPage, dependencies=[_need(Capability.AUDIT_READ)])
async def audit(
    store: StoreDep,
    action: Annotated[str | None, Query(max_length=100)] = None,
    actor: Annotated[str | None, Query(max_length=320)] = None,
    before: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditPage:
    return await store.audit(action_prefix=action, actor_email=actor, before=before, limit=limit)
