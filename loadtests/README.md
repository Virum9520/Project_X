# Load tests (C23 part B)

[k6](https://k6.io) scripts and SQL probes for the API, the worker and the database. They are
meant for **local or dev** environments. `k6/lib.js` refuses production-looking URLs unless
`I_KNOW_THIS_IS_PRODUCTION=yes` is set; do not set it. Scripts never create accounts or log in:
you paste short-lived Clerk session JWTs in as environment variables.

Install k6 with `brew install k6`. All commands run from the repo root.

| Script | What it exercises | Needs |
| --- | --- | --- |
| `k6/api.js` | `/healthz`, `/readyz` and, with a learner token, the learner read paths | API running; optional `K6_LEARNER_TOKEN` |
| `k6/db-connections.js` + `k6/db-connections.sql` | Connection-pool pressure through `/readyz` (a real `SELECT 1`) | API running; `psql` access to `DATABASE_URL` |
| `k6/worker-backlog.js` | Floods the signed ElevenLabs webhook, then watches the backlog drain on `/v1/admin/quality` | API and worker running with a **local** `ELEVENLABS_WEBHOOK_SECRET`; `K6_ADMIN_TOKEN` |
| `voice/peak-concurrency.sql` | Peak concurrent voice sessions per day, from real `sessions` rows | `psql` access; read-only |

Frame-time budgets for the 3D garden live in [frametime/README.md](frametime/README.md).

## Running

```bash
# API: smoke (1 VU, 30 s), load (ramp to 50 VUs), stress (ramp to 200 VUs)
k6 run loadtests/k6/api.js
k6 run -e PROFILE=load -e K6_LEARNER_TOKEN=... loadtests/k6/api.js

# Database connections: run the SQL probe in a second terminal while the burst runs
k6 run -e API_URL=http://localhost:8000 loadtests/k6/db-connections.js
watch -n 2 'psql "$DATABASE_URL" -f loadtests/k6/db-connections.sql'

# Worker backlog
k6 run -e ELEVENLABS_WEBHOOK_SECRET=... -e K6_ADMIN_TOKEN=... loadtests/k6/worker-backlog.js

# Peak voice concurrency over the last 14 days
psql "$DATABASE_URL" -v days=14 -f loadtests/voice/peak-concurrency.sql
```

## Reading the results

- **Connection arithmetic.** Each API process holds up to `pool_size + max_overflow` = 5 + 10
  connections (`sg_core/db.py`). Multiply by API replicas, add the worker, admin app and
  migrations, and keep the total below the Tiger Cloud connection limit with headroom. The peak
  seen in `db-connections.sql` is the number to compare against that limit.
- **Webhook ingest** must stay fast even when the worker is behind: it stores the event first and
  acknowledges (p95 under 500 ms in the script's thresholds).
- **Backlog** should drain: the oldest unprocessed event age on the Quality page should fall back
  under the script's threshold once the flood stops.
- **Voice concurrency.** Compare `peak-concurrency.sql` output with the concurrency allowance on
  your own ElevenLabs plan, which you should confirm in your ElevenLabs account. This repo does
  not assume a figure.

## Cleanup

`worker-backlog.js` posts events of type `load_test_ping`, which the worker does not handle and
marks `ignored`. They are real `provider_events` rows with provider `elevenlabs`. If you ran
against a shared database, remove them:

```sql
DELETE FROM provider_events WHERE event_type = 'load_test_ping';
```

Never run these scripts with a production webhook secret or against production data.
