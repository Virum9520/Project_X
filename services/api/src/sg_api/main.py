"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sg_api.admin.router import router as admin_console_router
from sg_api.agent_tools.get_briefing import router as get_briefing_router
from sg_api.agent_tools.search_my_documents import router as search_my_documents_router
from sg_api.auth import build_identity
from sg_api.future_self.router import router as future_self_router
from sg_api.garden.router import router as garden_router
from sg_api.garden.tool import router as query_analytics_router
from sg_api.knowledge.router import router as documents_router
from sg_api.middleware import AuditMiddleware, RequestContextMiddleware
from sg_api.routers import admin, health, me
from sg_api.sessions.router import router as sessions_router
from sg_api.webhooks.router import router as webhooks_router
from sg_core.db import get_sessionmaker
from sg_core.identity.db import seed_identity_catalog_committed
from sg_core.logging import configure_logging, get_logger
from sg_core.settings import Environment, get_settings

log = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.environment is not Environment.LOCAL)
    http = httpx.AsyncClient(timeout=httpx.Timeout(5.0))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if settings.identity_backend == "db":
            try:
                await seed_identity_catalog_committed(get_sessionmaker())
            except Exception as exc:  # e.g. database not migrated yet; the API still serves
                log.warning("identity.seed_failed", error=str(exc))
        yield
        await http.aclose()

    app = FastAPI(
        title="Skill Garden API",
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        lifespan=lifespan,
    )
    app.state.identity = build_identity(settings, http)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(AuditMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(admin.router)
    app.include_router(admin_console_router)
    app.include_router(sessions_router)
    app.include_router(webhooks_router)
    app.include_router(get_briefing_router)
    app.include_router(future_self_router)
    app.include_router(search_my_documents_router)
    app.include_router(documents_router)
    app.include_router(garden_router)
    app.include_router(query_analytics_router)
    return app


app = create_app()
