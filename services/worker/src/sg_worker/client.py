"""Hatchet client factory.

With HATCHET_CLIENT_TOKEN set we connect to Hatchet Cloud; in local development
without a token we run Hatchet's embedded engine (no Docker required).
"""

from functools import lru_cache

from hatchet_sdk import Hatchet

from sg_core.settings import Environment, get_settings


@lru_cache
def get_hatchet() -> Hatchet:
    settings = get_settings()
    token = settings.hatchet_client_token
    if token is not None and token.get_secret_value().strip():
        return Hatchet()  # reads HATCHET_CLIENT_TOKEN and related env vars
    if settings.environment in (Environment.LOCAL, Environment.TEST):
        return Hatchet.from_embedded()
    raise RuntimeError("HATCHET_CLIENT_TOKEN is required outside local/test environments")
