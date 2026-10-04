"""Owner analytics views and the read-only Tiger MCP role (C22).

Schema `analytics` (created by 0001) holds the only objects the owner assistant's Tiger MCP
connection may read. The views hold no model tables, so `alembic check` is unaffected.

- Every cost view reads only live `cost_entries` (`superseded_by_id IS NULL`), so a reconciled
  entry replaces the estimate it superseded instead of adding to it.
- No view exposes emails, names, transcripts or document text.
- Role `sg_mcp_readonly` is created NOLOGIN with SELECT on `analytics` only, read-only
  transactions and a 10s statement timeout. An operator gives it a login and password out of
  band (`ALTER ROLE sg_mcp_readonly LOGIN PASSWORD '...'`) and points the Tiger MCP sidecar at
  it. If the migration user may not create roles, it logs a NOTICE and skips role setup; rerun
  the `GRANT` statements below as an administrator.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "sg_mcp_readonly"

VIEWS: dict[str, str] = {
    "cost_entries_live": """
        SELECT id, created_at, (created_at AT TIME ZONE 'UTC')::date AS day, cost_center,
               component, provider, kind, usd_amount, native_unit, user_id, session_id
        FROM public.cost_entries
        WHERE superseded_by_id IS NULL
    """,
    "daily_cost": """
        SELECT (created_at AT TIME ZONE 'UTC')::date AS day, cost_center, component, provider,
               kind, count(*) AS entries, sum(usd_amount) AS usd_total
        FROM public.cost_entries
        WHERE superseded_by_id IS NULL
        GROUP BY 1, 2, 3, 4, 5
    """,
    "usage_daily": """
        SELECT (occurred_at AT TIME ZONE 'UTC')::date AS day, cost_center, component, provider,
               model, count(*) AS events, sum(input_tokens) AS input_tokens,
               sum(output_tokens) AS output_tokens, sum(connected_seconds) AS connected_seconds,
               sum(sandbox_seconds) AS sandbox_seconds
        FROM public.usage_events
        GROUP BY 1, 2, 3, 4, 5
    """,
    "sessions_daily": """
        SELECT (created_at AT TIME ZONE 'UTC')::date AS day, character, mode, status, is_test,
               count(*) AS sessions, sum(duration_seconds) AS total_duration_seconds
        FROM public.sessions
        GROUP BY 1, 2, 3, 4, 5
    """,
    "session_cost": """
        SELECT s.id AS session_id, (s.created_at AT TIME ZONE 'UTC')::date AS day, s.character,
               s.mode, s.status, s.is_test, c.cost_center, c.component, c.provider,
               sum(c.usd_amount) AS usd_total
        FROM public.sessions s
        JOIN public.cost_entries c ON c.session_id = s.id AND c.superseded_by_id IS NULL
        GROUP BY s.id, 2, s.character, s.mode, s.status, s.is_test, c.cost_center, c.component,
                 c.provider
    """,
    "calls_daily": """
        SELECT (scheduled_for AT TIME ZONE 'UTC')::date AS day, state, is_test,
               count(*) AS occurrences
        FROM public.call_occurrences
        GROUP BY 1, 2, 3
    """,
    "data_freshness": """
        SELECT 'usage_events' AS source, max(occurred_at) AS latest_at FROM public.usage_events
        UNION ALL SELECT 'cost_entries', max(created_at) FROM public.cost_entries
          WHERE superseded_by_id IS NULL
        UNION ALL SELECT 'sessions', max(created_at) FROM public.sessions
        UNION ALL SELECT 'call_occurrences', max(updated_at) FROM public.call_occurrences
    """,
}


def upgrade() -> None:
    for name, body in VIEWS.items():
        op.execute(f"CREATE OR REPLACE VIEW analytics.{name} AS {body}")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN;
            END IF;
            GRANT USAGE ON SCHEMA analytics TO {ROLE};
            GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO {ROLE};
            ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO {ROLE};
            ALTER ROLE {ROLE} SET default_transaction_read_only = on;
            ALTER ROLE {ROLE} SET statement_timeout = '10s';
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'could not set up role {ROLE}: grant SELECT on analytics manually';
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                REVOKE SELECT ON ALL TABLES IN SCHEMA analytics FROM {ROLE};
                REVOKE USAGE ON SCHEMA analytics FROM {ROLE};
                ALTER DEFAULT PRIVILEGES IN SCHEMA analytics REVOKE SELECT ON TABLES FROM {ROLE};
            END IF;
        EXCEPTION WHEN insufficient_privilege THEN
            RAISE NOTICE 'could not revoke privileges from {ROLE}';
        END
        $$
        """
    )
    for name in reversed(list(VIEWS)):
        op.execute(f"DROP VIEW IF EXISTS analytics.{name}")
