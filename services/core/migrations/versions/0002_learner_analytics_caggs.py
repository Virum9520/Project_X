"""Learner analytics continuous aggregates over `session_events` (C14).

Schema `learner_analytics` (created by 0001) holds read-only rollups the Garden Dashboard API
reads. They hold no model tables, so `alembic check` is unaffected.

- `daily_session_activity`: per learner, session and UTC day: event count and the first and last
  event time. The span is how practice time is measured when a session has no recorded duration.
- `weekly_session_activity`: hierarchical rollup of the daily view (sessions-days, events, active
  seconds) for the weekly charts and Sanjaya's recap.
- `daily_event_mix`: per learner, event type and UTC day: event counts.

All three are real-time (they union un-materialised recent rows), so a session that just ended is
visible at once. `WITH NO DATA` lets them be created inside the migration's transaction; the
refresh policies materialise them.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "learner_analytics"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW {SCHEMA}.daily_session_activity
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT
            user_id,
            session_id,
            time_bucket(INTERVAL '1 day', occurred_at) AS bucket,
            count(*) AS event_count,
            min(occurred_at) AS first_event_at,
            max(occurred_at) AS last_event_at
        FROM session_events
        GROUP BY user_id, session_id, time_bucket(INTERVAL '1 day', occurred_at)
        WITH NO DATA
        """
    )
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW {SCHEMA}.daily_event_mix
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT
            user_id,
            event_type,
            time_bucket(INTERVAL '1 day', occurred_at) AS bucket,
            count(*) AS event_count
        FROM session_events
        GROUP BY user_id, event_type, time_bucket(INTERVAL '1 day', occurred_at)
        WITH NO DATA
        """
    )
    op.execute(
        f"""
        CREATE MATERIALIZED VIEW {SCHEMA}.weekly_session_activity
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT
            user_id,
            time_bucket(INTERVAL '1 week', bucket) AS bucket,
            count(*) AS session_days,
            sum(event_count) AS event_count,
            sum(extract(epoch FROM last_event_at - first_event_at)) AS active_seconds
        FROM {SCHEMA}.daily_session_activity
        GROUP BY user_id, time_bucket(INTERVAL '1 week', bucket)
        WITH NO DATA
        """
    )
    for view, start, end, every in (
        ("daily_session_activity", "7 days", "1 hour", "1 hour"),
        ("daily_event_mix", "7 days", "1 hour", "1 hour"),
        ("weekly_session_activity", "35 days", "1 day", "6 hours"),
    ):
        op.execute(
            f"SELECT add_continuous_aggregate_policy('{SCHEMA}.{view}', "
            f"start_offset => INTERVAL '{start}', end_offset => INTERVAL '{end}', "
            f"schedule_interval => INTERVAL '{every}')"
        )


def downgrade() -> None:
    # The weekly view depends on the daily one, so drop it first.
    for view in ("weekly_session_activity", "daily_event_mix", "daily_session_activity"):
        op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {SCHEMA}.{view}")
