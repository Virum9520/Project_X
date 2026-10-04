"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sg_api.auth import build_identity
from sg_api.middleware import AuditMiddleware, RequestContextMiddleware
from sg_api.routers import admin, health, me
from sg_api.sessions.router import router as sessions_router
from sg_core.logging import configure_logging
from sg_core.settings import Environment, get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.environment is not Environment.LOCAL)
    http = httpx.AsyncClient(timeout=httpx.Timeout(5.0))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
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
    app.include_router(sessions_router)
    return app


app = create_app()
