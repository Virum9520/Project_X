# Hosting runbook (C05: simple managed hosting)

How the `dev` environment is wired, and how to set it up from scratch. Production AWS is C24.

```
Vercel ── web   (apps/web)    ─┐
       └─ admin (apps/admin)  ─┤ HTTPS + CORS
                               ▼
Railway ── api ───────────► Tiger Cloud (Postgres, TLS)
        ├─ worker ────────► Hatchet Cloud (gRPC, token)
        ├─ Redis  ◄──────── api (private network)
        └─ mcp-gateway (later, C22)
api / worker ─────────────► Cloudflare R2 (S3 API)
```

| Piece | Where it is defined |
|---|---|
| Python image for every service | `services/Dockerfile`; `SERVICE` selects the package and process (`services/docker-entrypoint.sh`) |
| Railway service config | `infra/railway/{api,worker,mcp-gateway}.json` (config as code) |
| Vercel project config | `apps/web/vercel.json`, `apps/admin/vercel.json` |
| R2 bucket CORS | `infra/r2/cors.json` |
| Health probes | API `GET /healthz` (liveness), `GET /readyz` (database and Redis); web and admin `GET /healthz` |
| Deploy smoke test | `scripts/smoke.py`, plus `python -m sg_worker.smoke` for the worker |

Deploys are automatic: Vercel and Railway both watch `main` (and Vercel builds a preview for every
PR). Nothing in GitHub Actions deploys. CI's `docker` job only proves that the images build and boot.

---

## 1. Cloudflare R2

1. In the Cloudflare dashboard, go to **R2 → Create bucket** and create `skill-garden-dev` with automatic location.
2. Go to **R2 → Manage API tokens → Create API token** and create an **Object Read & Write** token scoped to that bucket only. Note these values:
   - Access Key ID → `S3_ACCESS_KEY_ID`
   - Secret Access Key → `S3_SECRET_ACCESS_KEY`
   - S3 endpoint `https://<account-id>.r2.cloudflarestorage.com` → `S3_ENDPOINT_URL`
3. Set the bucket CORS so browsers can use presigned URLs (direct uploads start in C08). First
   replace `REPLACE_WITH_WEB_DOMAIN` in `infra/r2/cors.json` with the web app's domain, then run:
   ```bash
   npx wrangler r2 bucket cors set skill-garden-dev --file infra/r2/cors.json
   ```
4. Keep the bucket **private**: no public bucket URL and no `r2.dev` subdomain. All access goes through presigned URLs.

## 2. Hatchet Cloud

1. Create a tenant (for example `skill-garden-dev`) at cloud.onhatchet.run.
2. Go to **Settings → API Tokens → Create**. The value is `HATCHET_CLIENT_TOKEN`.
   Outside `local` and `test`, the worker refuses to start without it.

## 3. Railway (api, worker, Redis)

Create one project called `skill-garden`. Its default environment is the `dev` environment for now.

### 3.1 Redis
In the project canvas, choose **+ Create → Database → Redis**. Leave it private: no public networking.

### 3.2 Shared variables
Go to **Project Settings → Shared Variables** for the environment and add:

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `dev` |
| `LOG_LEVEL` | `INFO` |
| `DATABASE_URL` | Tiger service URL as given (`postgres://…?sslmode=require` is normalized automatically) |
| `S3_ENDPOINT_URL` | `https://<account-id>.r2.cloudflarestorage.com` |
| `S3_BUCKET` | `skill-garden-dev` |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | From the R2 token |
| `S3_REGION` | `auto` |
| `HATCHET_CLIENT_TOKEN` | From Hatchet Cloud |
| `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_WEBHOOK_SECRET`, `E2B_API_KEY` | As the providers are wired in (C03, C06). Empty is fine for now |
| `CLERK_ISSUER`, `ADMIN_OWNER_EMAILS` | Once C01 lands |

### 3.3 `api` service
1. Choose **+ Create → GitHub Repo → Project_X**, then rename the service to `api`.
2. Under **Settings → Source**:
   - Leave **Root Directory** empty, because the image builds from the repo root.
   - Set **Branch** to `main`.
   - Turn on **Wait for CI**, so a red build never deploys.
3. Under **Settings → Config-as-code**, set the path to `/infra/railway/api.json`. It must be the
   absolute path from the repo root.
4. Under **Variables**, add:
   - every shared variable, using **Add all shared variables**, or one by one as `${{shared.NAME}}`
   - `SERVICE` = `sg_api`. It is read as a build arg and picks the package and process.
   - `SERVICE_NAME` = `api`
   - `REDIS_URL` = `${{Redis.REDIS_URL}}`, the private hostname
   - `CORS_ORIGINS` = `https://<web-domain>,https://<admin-domain>`, filled in after step 4
   - Optional, dev only: `CORS_ORIGIN_REGEX` = `https://skill-garden-(web|admin)-[a-z0-9-]+-<vercel-team-slug>\.vercel\.app`, to allow PR preview deployments
5. Under **Settings → Networking**, choose **Generate Domain**. Use that URL as `NEXT_PUBLIC_API_URL` on Vercel.
6. Deploy. Railway gates the release on `GET /readyz`, so a bad `DATABASE_URL` or `REDIS_URL`
   fails the deploy instead of serving errors. Check that `/docs` loads; it is disabled only when `ENVIRONMENT=prod`.

### 3.4 `worker` service
1. Choose **+ Create → GitHub Repo → Project_X** and rename the service to `worker`.
2. Use the same source settings as the API: empty root directory, branch `main`, **Wait for CI** on.
3. Set the config-as-code path to `/infra/railway/worker.json`.
4. Under **Variables**, add all shared variables, plus `SERVICE` = `sg_worker` and `SERVICE_NAME` = `worker`.
5. Don't create a public domain. The worker only makes outbound connections to Hatchet.

### 3.5 `mcp-gateway` service (optional until C22)
Same steps as the worker, but use `/infra/railway/mcp-gateway.json` and set `SERVICE` = `sg_mcp_gateway`.
If it should only be reachable from inside the project, also set `HOST` = `::` so it listens on the
private network.

### 3.6 Database migrations (when C02 lands)
Add this to `infra/railway/api.json` under `deploy`, so migrations run once per release before
traffic shifts. The worker must not also run them.
```json
"preDeployCommand": ["alembic upgrade head"]
```
Adjust the command to wherever C02 puts `alembic.ini`. The entrypoint runs any arguments as-is.

## 4. Vercel (web, admin)

Create two projects from the same repo:

| Setting | web | admin |
|---|---|---|
| Project name | `skill-garden-web` | `skill-garden-admin` |
| Root Directory | `apps/web` | `apps/admin` |
| Framework preset | Next.js (from `vercel.json`) | Next.js |
| Node.js version | 22.x (matches `.nvmrc`) | 22.x |
| Include files outside the root directory | **On** (needs `packages/*`) | **On** |
| Skip deployments when there are no changes to the root directory or its dependencies | **On** | **On** |

Environment variables (Production and Preview):

| Variable | Value | Why |
|---|---|---|
| `ENABLE_EXPERIMENTAL_COREPACK` | `1` | The repo pins `pnpm@12` through `packageManager`. Vercel's built-in pnpm stops at 10 |
| `NEXT_PUBLIC_API_URL` | Railway API URL, no trailing slash | Inlined at build time, so redeploy after changing it |

Clerk keys get added here when C01 lands.

Things to know:
- **Preview deployments are behind Vercel Authentication** by default. Production domains are not.
  To smoke-test a preview from the command line, create a **Protection Bypass for Automation**
  secret, or test production instead.
- `vercel.json` sets security headers. The admin project also sends `X-Frame-Options: DENY` and
  `noindex`.
- Once deployed, put both production URLs into the API's `CORS_ORIGINS` (step 3.3) and redeploy the API.

## 5. Smoke test

Run from your machine after each deploy:

```bash
uv run scripts/smoke.py \
  --api https://<api>.up.railway.app \
  --web https://skill-garden-web.vercel.app \
  --admin https://skill-garden-admin.vercel.app \
  --commit "$(git rev-parse --short origin/main)"
```

It checks:
- API `/healthz`, `/readyz` (database and Redis up) and the `X-Request-ID` header.
- A CORS preflight from the web origin.
- Web and admin `/healthz` and `/`.
- That each tier reports the expected commit, and that each app's `NEXT_PUBLIC_API_URL` points at
  the API you passed.

Two optional add-ons:

```bash
# R2: put, get, presigned GET, then delete an object (export the S3_* variables first)
uv run scripts/smoke.py --r2

# Worker: run system.ping through Hatchet Cloud on the deployed worker
HATCHET_CLIENT_TOKEN=... ENVIRONMENT=dev uv run --package sg_worker python -m sg_worker.smoke
```

## 6. Rollback
- **Railway:** open the service's **Deployments** tab, then choose **⋯ → Rollback** on the last good deployment.
- **Vercel:** open **Deployments**, choose **⋯ → Instant Rollback**. `NEXT_PUBLIC_*` values are part
  of each build, so a rollback also restores the old values.
- Never roll back past a migration without a matching downgrade (C02).

## 7. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Railway deploy stuck on health check, `/readyz` returns `database: false` | Tiger IP allowlist is on: Railway egress IPs aren't static on the Hobby plan, so allow all IPs or use Railway static IPs (Pro). Or the URL is wrong |
| `redis: false` | `REDIS_URL` doesn't reference `${{Redis.REDIS_URL}}`, or Redis is in a different environment |
| Worker crash-loops with `HATCHET_CLIENT_TOKEN is required` | Token missing, or `ENVIRONMENT` is not `local` or `test` |
| Vercel install fails with an unsupported pnpm version | `ENABLE_EXPERIMENTAL_COREPACK=1` is missing |
| Vercel build can't find `@sg/ui` or `@sg/contracts` | "Include files outside the root directory" is off |
| Browser shows a CORS error | Origin missing from `CORS_ORIGINS` (exact match, no trailing slash) or not matched by `CORS_ORIGIN_REGEX` |
| Smoke test gets 401 on a Vercel preview | Vercel Authentication. Use the bypass secret or test production |
