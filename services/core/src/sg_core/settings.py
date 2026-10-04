"""Typed runtime configuration loaded from the environment (12-factor).

Every service reads configuration through `get_settings()`. Secrets are
`SecretStr` so they never appear in logs or reprs.
"""

import json
from enum import StrEnum
from functools import lru_cache
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    DEV = "dev"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.LOCAL
    service_name: str = "skill-garden"
    log_level: str = "INFO"
    # Commit being served; Railway injects RAILWAY_GIT_COMMIT_SHA automatically.
    git_sha: str | None = Field(
        default=None, validation_alias=AliasChoices("GIT_SHA", "RAILWAY_GIT_COMMIT_SHA")
    )

    # Data
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://postgres:postgres@localhost:5432/skill_garden"),
    )
    # Optional: when unset, Redis-backed features stay off and /readyz skips the check.
    redis_url: str | None = None

    # Object storage (S3-compatible: MinIO locally, Cloudflare R2 now, AWS S3 later)
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_bucket: str = "skill-garden-local"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_region: str = "auto"

    # Providers
    elevenlabs_api_key: SecretStr | None = None
    elevenlabs_webhook_secret: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    e2b_api_key: SecretStr | None = None
    hatchet_client_token: SecretStr | None = None

    # Auth (Clerk) — one application shared by the learner and admin apps
    clerk_issuer: str | None = None
    # Owner-console allowlist; checked server-side on every admin request.
    admin_owner_emails: Annotated[list[str], NoDecode] = []

    # CORS: comma-separated (or JSON list) exact origins, plus an optional regex for
    # preview deployments, e.g. https://skill-garden-web-[a-z0-9-]+-myteam\.vercel\.app
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:3001",
    ]
    cors_origin_regex: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> object:
        return normalize_database_url(value) if isinstance(value, str) else value

    @field_validator("admin_owner_emails", mode="before")
    @classmethod
    def _split_emails(cls, value: object) -> object:
        if isinstance(value, str):
            return [e.strip().lower() for e in value.split(",") if e.strip()]
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            if value.lstrip().startswith("["):
                return json.loads(value)
            return [o.strip().rstrip("/") for o in value.split(",") if o.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PROD


def normalize_database_url(url: str) -> str:
    """Accept provider-style URLs (e.g. Tiger Cloud's `postgres://...?sslmode=require`).

    Rewrites the scheme to the asyncpg driver and translates libpq's `sslmode` into
    asyncpg's `ssl` query parameter.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    query = []
    for key, val in parse_qsl(parts.query, keep_blank_values=True):
        query.append(("ssl", val) if key == "sslmode" else (key, val))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@lru_cache
def get_settings() -> Settings:
    return Settings()
