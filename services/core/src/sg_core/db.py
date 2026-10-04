"""Async SQLAlchemy engine and session factory (Tiger Cloud / TimescaleDB)."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sg_core.settings import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        str(settings.database_url),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def session_scope() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed by the caller."""
    async with get_sessionmaker()() as session:
        yield session


async def ping() -> bool:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True
