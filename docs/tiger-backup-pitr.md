# Tiger Cloud backup and point-in-time recovery

Skill Garden's system of record is one Tiger Cloud (managed Postgres with TimescaleDB and
pgvector) service. Redis and Hatchet hold no durable product state, and documents live in R2.

Verify the retention numbers in the Tiger console for your plan before relying on them: they
vary by plan and I could not check the live service from here.

## What Tiger provides

- Continuous WAL archiving with automated base backups, which enables point-in-time recovery
  (PITR) to any moment inside the retention window.
- A restore creates a **new service** (a fork) from a backup or a chosen timestamp. The original
  service is untouched, so a restore is also how to inspect data as of before an incident.
- High-availability replicas (a paid option) protect against node failure, not against bad
  writes: a bad migration replicates. PITR is the defence for that.

## Recovery targets

| Scenario | Action | Expected loss |
|---|---|---|
| Bad migration or bulk delete | Fork at a timestamp just before the event, validate, then repoint `DATABASE_URL` | Writes since the timestamp |
| Table dropped by mistake | Fork before the drop, `pg_dump` the table, restore it into the live service | None for other tables |
| Node or zone failure | Rely on the managed service (HA replica if enabled) | Near zero |
| Credential leak | Rotate the service password in Tiger, update Railway and Vercel variables, redeploy | None |

## Restore runbook

1. Note the incident time (UTC). Pick a restore time a few minutes earlier.
2. Tiger console, the service, Operations, fork or restore: choose point-in-time and enter the
   timestamp. Wait for the new service to report ready.
3. Connect with the new `postgres://...?sslmode=require` URL and validate:
   `uv run alembic current` shows the expected head, row counts for `users`, `garden_revisions`,
   `evidence_items` look right, and the latest `session_events` row is before the restore time.
4. Either repoint (set `DATABASE_URL` in Railway for api, worker and mcp-gateway, redeploy, then
   check `GET /readyz`) or copy only the damaged tables back with `pg_dump` and `pg_restore`.
5. Hypertables (`session_events`, `usage_events`) and continuous aggregates come back with the
   fork. Refresh the `learner_analytics` caggs if they were mid-refresh.
6. Write down what happened in `docs/PROGRESS.md` Log, and keep the old service until the new one
   has run clean for a day.

## What is not covered

- Learner uploads in R2 (enable bucket versioning, or accept that a deleted object is gone).
- Clerk accounts (Clerk holds them; export if required).
- Secrets (kept in Railway and Vercel, not in Postgres).

## Drill before launch

Fork the dev service to a point 10 minutes in the past, run the validation queries in step 3,
time the whole exercise and record it here. Until that is done, treat the recovery time as
unknown.

## Before the AWS migration (C24)

Plan the move with a logical dump and restore into the new database (or Tiger's replication), and
keep Tiger running read-only for a rollback window.
