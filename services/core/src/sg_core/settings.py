"""Typed runtime configuration loaded from the environment (12-factor).

Every service reads configuration through `get_settings()`. Secrets are
`SecretStr` so they never appear in logs or reprs.
"""

import os
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

    # Observability (C23). Everything is off until configured: no DSN or endpoint, no-op.
    sentry_dsn: SecretStr | None = None
    sentry_traces_sample_rate: float = 0.0
    # OTLP/HTTP collector base URL (e.g. https://otlp.example.com); headers as "k=v,k2=v2".
    otel_exporter_otlp_endpoint: str | None = None
    otel_exporter_otlp_headers: SecretStr | None = None
    otel_traces_sample_ratio: float = 0.1

    # Data
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://postgres:postgres@localhost:5432/skill_garden"),
    )
    # Optional: when unset, Redis-backed features stay off and /readyz skips the check.
    redis_url: str | None = None

    # Curriculum YAML root (`<dir>/<key>/<version>/`); defaults to the repo's `curriculum/`.
    curriculum_dir: Path | None = None

    # Object storage (S3-compatible: MinIO locally, Cloudflare R2 now, AWS S3 later).
    # `OBJECT_STORE=local` keeps objects on disk under `LOCAL_STORAGE_DIR` for machines without
    # MinIO (no Docker); it is refused outside the local and test environments.
    object_store: Literal["s3", "local"] = "s3"
    local_storage_dir: Path = Path(".local-storage")
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
    # ElevenLabs voice ID Sanjaya narrates the weekly recap with (Voice Design result, C20).
    sanjaya_voice_id: str | None = None
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
    # Evidence pipeline (C11). The full post-call judge; the fast live micro-judge (a small,
    # quick model, graded in a few seconds); and the micro-judge's time budget.
    judge_model: str = "anthropic/claude-sonnet-4.5"
    micro_judge_model: str = "openai/gpt-4o-mini"
    micro_judge_timeout_seconds: float = 4.0
    # Accounts graded under `rules/profile.demo.yaml` (compressed review clock). Demo and test
    # accounts only; matched against `users.email` server-side, never from client input.
    demo_account_emails: Annotated[list[str], NoDecode] = []

    # Monthly spend caps in USD, enforced by budget holds (sg_core.economics).
    learner_monthly_budget_usd: Decimal = Decimal("7.50")
    developer_monthly_budget_usd: Decimal = Decimal("25")
    owner_assistant_monthly_budget_usd: Decimal = Decimal("10")

    # Owner assistant and MCP gateway (C22). Upstream MCP servers are optional: a missing one
    # yields an explicit partial answer. The ElevenLabs hosted MCP uses OAuth; the backend holds
    # the access token the owner granted (never sent to the browser or the model). Tiger MCP is a
    # sidecar (HTTP transport) connected as a dedicated read-only role limited to `analytics.*`.
    elevenlabs_mcp_url: str | None = None
    elevenlabs_mcp_access_token: SecretStr | None = None
    tiger_mcp_url: str | None = None
    tiger_mcp_token: SecretStr | None = None
    tiger_mcp_service_id: str | None = None
    # Model for the assistant (None = `llm_default_model`) and its per-question limits.
    owner_assistant_model: str | None = None
    owner_assistant_max_steps: int = 6  # model turns per question; also bounds tool calls
    owner_assistant_max_tool_calls: int = 8
    owner_assistant_max_rows: int = 200
    owner_assistant_max_tool_bytes: int = 24_000
    owner_assistant_tool_timeout_seconds: float = 20.0
    owner_assistant_max_concurrent_queries: int = 2
    owner_assistant_max_output_tokens: int = 1200
    # Budget held before each model turn (settled at the real cost, released on failure).
    owner_assistant_turn_hold_usd: Decimal = Decimal("0.15")

    # Owner console "Call now" (C21): where a developer test call may go, how often, how long.
    # "web" = the web call channel; anything else must be a verified E.164 test number.
    call_now_approved_targets: Annotated[list[str], NoDecode] = ["web"]
    call_now_cooldown_seconds: int = 60
    call_now_max_duration_seconds: int = 300
    # Bhima accountability calls (C18). The consent version learners must have accepted, the
    # local-time quiet window (no calls), how long a web call rings before it is missed, how late
    # the dispatcher may still start a call after an outage, and the per-minute budget estimate.
    bhima_consent_version: str = "bhima-calls-v1"
    bhima_quiet_start: str = "21:30"
    bhima_quiet_end: str = "08:00"
    bhima_ring_timeout_seconds: int = 45
    bhima_late_grace_seconds: int = 20 * 60
    bhima_max_concurrent_calls: int = 5
    bhima_cost_per_minute_usd: Decimal = Decimal("0.12")
    # Web Push (VAPID). Generate a key pair with `npx web-push generate-vapid-keys`.
    vapid_public_key: str | None = None
    vapid_private_key: SecretStr | None = None
    vapid_subject: str = "mailto:owner@example.com"

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

    @field_validator("admin_owner_emails", "demo_account_emails", mode="before")
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
    def dev_identity_allowed(self) -> bool:
        """May a request name its own user (`X-Dev-User-Id`)? Only on a developer machine.

        `ENVIRONMENT` defaults to `local`, so a hosted deploy that forgets to set it must not
        turn this on: Railway and Vercel inject their own variables, which keep it off.
        """
        hosted = any(
            os.environ.get(name)
            for name in ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_NAME", "VERCEL", "VERCEL_ENV")
        )
        return self.environment in (Environment.LOCAL, Environment.TEST) and not hosted

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
