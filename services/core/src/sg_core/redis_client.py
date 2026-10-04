"""Shared async Redis client (Railway Redis in hosted envs; optional locally)."""

from functools import lru_cache

from redis.asyncio import Redis

from sg_core.settings import get_settings


@lru_cache
def get_redis() -> Redis:
    """Return the process-wide client. Raises if REDIS_URL is not configured."""
    url = get_settings().redis_url
    if not url:
        raise RuntimeError("REDIS_URL is not configured")
    return Redis.from_url(url, socket_connect_timeout=3, socket_timeout=3, health_check_interval=30)


async def ping() -> bool:
    return bool(await get_redis().ping())
