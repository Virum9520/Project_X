-- Run with psql against the target database while db-connections.js or worker-backlog.js runs:
--   psql "$DATABASE_URL" -f loadtests/k6/db-connections.sql   (add \watch 2 to repeat)
-- Read-only.
SELECT current_setting('max_connections')::int AS max_connections,
       count(*)                                  AS total,
       count(*) FILTER (WHERE state = 'active')  AS active,
       count(*) FILTER (WHERE state = 'idle')    AS idle,
       count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_txn,
       count(*) FILTER (WHERE wait_event_type = 'Lock')      AS waiting_on_locks
FROM pg_stat_activity
WHERE datname = current_database();

-- Who holds them: one row per application_name (Railway service, worker, psql).
SELECT coalesce(nullif(application_name, ''), '(unset)') AS application, count(*) AS connections
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY 1
ORDER BY 2 DESC;
