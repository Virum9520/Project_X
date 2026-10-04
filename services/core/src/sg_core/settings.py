"""Typed runtime configuration loaded from the environment (12-factor).

Every service reads configuration through `get_settings()`. Secrets are
`SecretStr` so they never appear in logs or reprs.
"""

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
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

    # Curriculum YAML root (`<dir>/<key>/<version>/`); defaults to the repo's `curriculum/`.
    curriculum_dir: Path | None = None

    # Object storage (S3-compatible: MinIO locally, Cloudflare R2 now, AWS S3 later)
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_bucket: str = "skill-garden-local"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_region: str = "auto"
    # Largest accepted document upload (C08).
    max_upload_bytes: int = 25 * 1024 * 1024

    # Providers
    elevenlabs_api_key: SecretStr | None = None
    elevenlabs_webhook_secret: SecretStr | None = None
    elevenlabs_base_url: str = "https://api.elevenlabs.io"
    # Character key -> ElevenLabs agent ID (JSON). Print it with `uv run sg-agents ids`.
    elevenlabs_agent_ids: dict[str, str] = {}
    # Signs the session-scoped tokens that agents send to /v1/agent-tools/* (server tools).
    agent_tool_token_secret: SecretStr | None = None
    agent_tool_token_ttl_seconds: int = 3600
    openrouter_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    e2b_api_key: SecretStr | None = None
    hatchet_client_token: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openai_base_url: str = "https://api.openai.com/v1"
    # Default models (OpenRouter slugs / OpenAI embedding model); 1536 dims match the schema.
    llm_default_model: str = "anthropic/claude-sonnet-4.5"
    llm_fallback_models: Annotated[list[str], NoDecode] = ["openai/gpt-4o-mini"]
    embedding_model: str = "text-embedding-3-small"

    # Monthly spend caps in USD, enforced by budget holds (sg_core.economics).
    learner_monthly_budget_usd: Decimal = Decimal("7.50")
    developer_monthly_budget_usd: Decimal = Decimal("25")
    owner_assistant_monthly_budget_usd: Decimal = Decimal("10")

    # Owner console "Call now" (C21): where a developer test call may go, how often, how long.
    # "web" = the web call channel; anything else must be a verified E.164 test number.
    call_now_approved_targets: Annotated[list[str], NoDecode] = ["web"]
    call_now_cooldown_seconds: int = 60
    call_now_max_duration_seconds: int = 300

    # Auth (Clerk) — one application shared by the learner and admin apps
    # Frontend API URL, e.g. https://<slug>.clerk.accounts.dev; JWKS lives under it.
    clerk_issuer: str | None = None
    # Backend API key: used to read a user's verified email and MFA state.
    clerk_secret_key: SecretStr | None = None
    clerk_api_url: str = "https://api.clerk.com"
    # Accepted `azp` claims (the origins of our own frontends). Empty means "same as CORS".
    clerk_authorized_parties: Annotated[list[str], NoDecode] = []
    # Owner-console allowlist; checked server-side on every admin request.
    admin_owner_emails: Annotated[list[str], NoDecode] = []
    # Browser origins allowed to send admin mutations (CSRF origin check).
    admin_origins: Annotated[list[str], NoDecode] = ["http://localhost:3001"]
    # "db": grants, audit log and the users/profiles mirror live in Postgres. "memory": no
    # persistence (static grants, log-only audit), for runs without a database.
    identity_backend: Literal["db", "memory"] = "db"

    # CORS: exact origins (comma-separated), plus an optional regex for preview deployments,
    # e.g. https://skill-garden-web-[a-z0-9-]+-myteam\.vercel\.app
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://localhost:3001",
    ]
    cors_origin_regex: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> object:
        return normalize_database_url(value) if isinstance(value, str) else value

    @field_validator("curriculum_dir", mode="before")
    @classmethod
    def _empty_curriculum_dir(cls, value: object) -> object:
        # `CURRICULUM_DIR=` (as in .env.example) means "use the default", not Path(".").
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("admin_owner_emails", mode="before")
    @classmethod
    def _split_emails(cls, value: object) -> object:
        if isinstance(value, str):
            return [e.strip().lower() for e in value.split(",") if e.strip()]
        return value

    @field_validator(
        "clerk_authorized_parties",
        "admin_origins",
        "cors_origins",
        "llm_fallback_models",
        "call_now_approved_targets",
        mode="before",
    )
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip().rstrip("/") for o in value.split(",") if o.strip()]
        return value

    @field_validator("clerk_issuer", mode="before")
    @classmethod
    def _strip_issuer(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().rstrip("/") or None
        return value

    @property
    def authorized_parties(self) -> list[str]:
        return self.clerk_authorized_parties or self.cors_origins

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
