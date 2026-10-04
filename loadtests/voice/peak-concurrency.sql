-- Peak concurrent voice sessions per day, from the `sessions` table (excludes Call now tests
-- unless you pass include_tests). Compare the result with the ElevenLabs plan's concurrency limit.
--   psql "$DATABASE_URL" -v days=14 -f loadtests/voice/peak-concurrency.sql
-- Read-only.
WITH s AS (
  SELECT started_at AS t, 1 AS d FROM sessions
   WHERE started_at > now() - (:'days' || ' days')::interval AND NOT is_test AND started_at IS NOT NULL
  UNION ALL
  SELECT coalesce(ended_at, started_at + make_interval(secs => coalesce(duration_seconds, 0))), -1
    FROM sessions
   WHERE started_at > now() - (:'days' || ' days')::interval AND NOT is_test AND started_at IS NOT NULL
),
running AS (
  SELECT t, sum(d) OVER (ORDER BY t, d) AS concurrent FROM s WHERE t IS NOT NULL
)
SELECT date_trunc('day', t) AS day, max(concurrent) AS peak_concurrent_sessions
FROM running
GROUP BY 1
ORDER BY 1;
