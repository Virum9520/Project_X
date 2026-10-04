"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sg_api.middleware import RequestContextMiddleware
from sg_api.routers import health
from sg_core.logging import configure_logging
from sg_core.settings import Environment, get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.environment is not Environment.LOCAL)

    app = FastAPI(
        title="Skill Garden API",
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router)
    return app


app = create_app()
