# Skill Garden: Build Progress

The **single shared source of truth** for parallel build sessions. Follow the protocol in
[CLAUDE.md](../CLAUDE.md) whenever you claim, finish or block a component. The full spec is in
[build-plan.md](build-plan.md).

**Status values:** `todo` · `claimed` · `in-progress` · `in-review` (PR open) · `done` · `blocked`

**Ready** means every component listed under **Depends on** is `done`. Some components say "can
start on mocks". Their UI or pure logic can be built against stub data before the prerequisite is
done, and the real integration waits.

## Component board

| ID | Component | Phase | Depends on | Status | Owner (branch) | Notes |
|---|---|---|---|---|---|---|
| C00 | Repo, monorepo and tooling foundations | 0 | none | done | `chore/phase-0-foundations` | Tiger dev DB connected (PG 18, timescaledb 2.30, vector 0.8) |
| C01 | Identity and RBAC: Clerk (one app), JWKS verification, admin allowlist plus MFA, capabilities, audit log | 1 | C00, C02 | done | `feat/c01-identity` | Owner allowlist + MFA enforced by the API and the console. Built against interfaces while C02 was in flight; **follow-up now that C02 tables exist**: DB-backed `GrantStore` (`admin_users`, `admin_role_grants`, `role_capabilities`; seed `capabilities` from `sg_core.identity.Capability`), `AuditSink` writing `audit_log`, and `users`/`profiles` upsert (onboarding answers live in Clerk `publicMetadata.onboarding` until then) |
| C02 | DB baseline: Alembic, extensions, core tables, hypertables | 1 | C00 | done | `feat/c02-db-baseline` | Baseline `0001` is applied to the dedicated Skill Garden Tiger service. The old dev DB holds prototype tables, so point `DATABASE_URL` at the new service |
| C03 | Provider adapters (ElevenLabs, OpenRouter, OpenAI, E2B, ObjectStore), usage ledger, budget reservations | 2 | C02 | todo | | |
| C04 | Job infrastructure: Hatchet workflows, idempotency keys, webhook ingestion (HMAC) into `provider_events` | 2 | C02 | todo | | |
| C05 | Simple hosting: Vercel (web, admin), Railway (api, worker, Redis), R2 | 2 | C00 | done | `feat/c05-hosting` | Repo side done: image, Railway/Vercel config, probes, smoke script, runbook ([hosting.md](hosting.md)). Account provisioning follows the runbook |
| C06 | ElevenLabs agents-as-code, Voice Design voices, conversation-token endpoint, spikes (a)–(e) | 3 | C00 | done | `feat/c06-elevenlabs-agents` | 8 agents, 15 tools, 14 agent tests, `sg-agents` CLI, ADRs 0001–0005. `POST /v1/sessions` uses Clerk auth (C01); session row not yet persisted (C02 tables exist) and the briefing is a stub until C09. **Follow-up (owner, needs `ELEVENLABS_API_KEY`):** `sg-agents voices design`/`create`, set dev `api_base_url` after C05, first `sg-agents sync`, commit registries, ADR live checks |
| C07 | Curriculum `cs-core@v1` (about 80 concepts, prerequisite edges, rubrics) as YAML plus a loader | 4 | none | todo | | Content-only and ready to start |
| C08 | Knowledge ingestion pipeline (upload, extract, map, embed, activate) | 4 | C02, C03, C04, C07 | todo | | |
| C09 | Memory Persistence Engine: append-only memories, briefing builder, projections | 5–6 | C02 | todo | | Core USP backend |
| C10 | Rules engine: deterministic, versioned, `profile.yaml` and `profile.demo.yaml` | 5 | C07 | todo | | Pure Python, can start on mocks |
| C11 | Evidence and judge pipeline: post-call workflow, micro-judge, validation, garden revisions | 5 | C03, C04, C09, C10 | todo | | |
| C12 | Drona session loop: voice stage UI, server and client tools, Teach-back, live provisional growth over SSE | 5 | C01, C06, C11 | todo | | UI can start on mocks |
| C13 | 3D garden scene and generator in `packages/three` (island, plants, growth animation, semantic zoom) | 6 | C00 | claimed | `feat/c13-3d-garden-scene` | Ready to start; uses mock garden state |
| C14 | Garden Dashboard: analytics API, dashboard shell, KPI and insights rails, timeline, time travel, memory panel, Ask Sanjaya | 6 | C09, C10, C13 | todo | | USP. UI can start on mocks |
| C15 | VRM avatars and lip-sync (`onAudioAlignment` to visemes) | 6 | C00 | todo | | Ready to start |
| C16 | Arjuna technical interview: résumé and job description parsing, problem bank, Monaco, E2B tests, Scribe captions | 7 | C11, C12 | todo | | |
| C17 | Vidura HR interview and Panel interview | 8 | C12 | todo | | |
| C18 | Bhima accountability: commitments, scheduler, dispatcher, `WebCallChannel`, retention calls | 9 | C01, C03, C04, C06 | todo | | `PhoneCallChannel` is a stub only |
| C19 | Krishna and Future-Self voice (consent checked with Scribe, IVC, revoke) | 10 | C01, C03, C06 | todo | | |
| C20 | Living soundscape (Music and SFX asset script, audio engine) and Sanjaya weekly recap | 11 | C03 (assets), C11 and C13 (recap) | todo | | The asset script can start once C03 is done |
| C21 | Owner Console: 6 pages, Call now | 12 | C01, C03 | todo | | |
| C22 | MCP gateway and owner assistant (ElevenLabs hosted MCP, Tiger MCP read-only) | 12 | C21 | todo | | |
| C23 | Hardening and demo: observability, security review, load tests, judge calibration, demo seed | 13 | most | todo | | The landing page (`apps/web/src/app/page.tsx`, `apps/web/src/app/_landing/`) was built early in the C01 PR. **Review it when C23 starts**: copy, three.js hero performance budget, demo path |
| C24 | Production AWS migration (Terraform, ECS) | 14 | C23 | todo | | Later |

**Ready now** (dependencies met): C03, C04, C07, C09, C13, C15.

## Shared interfaces
When a component exposes something others build on (an API route, table, TS type, Python module,
event name or SSE channel), record it here in the same PR.

| Interface | Provided by | Location | Notes |
|---|---|---|---|
| `Settings` / `get_settings()` | C00 | `services/core/src/sg_core/settings.py` | Accepts Tiger's `postgres://…?sslmode=require` URLs |
| Async DB engine and session | C00 | `services/core/src/sg_core/db.py` | |
| Hatchet client (Cloud, or embedded locally) | C00 | `services/worker/src/sg_worker/client.py` | |
| Domain enums (`Character`, `Dimension`, `PlantStage`) | C00 | `packages/contracts/src/index.ts` | |
| Design tokens | C00 | `packages/ui/src/index.ts`, `apps/*/src/app/globals.css` | |
| `GET /v1/me`, `GET /v1/admin/me` | C01 | `services/api/src/sg_api/routers/{me,admin}.py` | Bearer = Clerk session token. Admin routes need owner allowlist or grant, verified email, and a second factor in the session |
| Auth dependencies | C01 | `services/api/src/sg_api/auth/` | `current_session`, `current_admin`, `require_capability(cap)`, `admin_origin_guard` (CSRF), `record_audit(...)`. Mount admin routers under `/v1/admin` so `AuditMiddleware` audits every mutation |
| `sg_core.identity` | C01 | `services/core/src/sg_core/identity/` | `ClerkTokenVerifier` (JWKS), `ClerkUserDirectory`, `Capability`, `GrantStore`, `AuditSink`/`AuditEvent`; for the API and the MCP gateway |
| Identity contracts | C01 | `packages/contracts/src/identity.ts` | `Capability`, `Me`, `AdminMe`, `OnboardingProfile`; mirror of the Python side |
| Next auth helpers | C01 | `apps/web/src/lib/{session,api}.ts`, `apps/admin/src/lib/{owner,api}.ts` | `requireOnboardedLearner()`, `requireOwner()`, `apiGet()` (server-side, forwards the Clerk token). `src/proxy.ts` in each app is optimistic only |
| Clerk appearance | C01 | `packages/ui/src/index.ts` (`clerkAppearance`) | |
| SQLAlchemy models for all 37 core tables (`Base`, `HYPERTABLES`, `EMBEDDING_DIM`=1536) | C02 | `services/core/src/sg_core/models/` | One module per domain: identity, curriculum, knowledge, sessions, evidence, memory, accountability, economics. Table semantics are owned by the component named in each module docstring |
| Python domain enums (`Character`, `Dimension`, `PlantStatus`, `MemoryLayer`, `CallState`, …) | C02 | `services/core/src/sg_core/models/enums.py` | Stored as VARCHAR(40) + named CHECK `ck_<table>_<column>`. Adding a value needs a migration that recreates the CHECK. `Character`/`PlantStatus` mirror `packages/contracts` (a test enforces it) |
| Alembic (async, URL from `get_settings()`) | C02 | `alembic.ini`, `services/core/migrations/` | Baseline revision `0001`. Run from the repo root |
| Hypertables `session_events`, `usage_events` | C02 | migration `0001` | Partitioned on `occurred_at`, 7-day chunks, PK `(id, occurred_at)`. No FKs may point at them. `usage_events` dedupes on `(idempotency_key, occurred_at)` |
| Vector columns `chunks.embedding`, `memories.embedding` | C02 | `vector(1536)`, HNSW cosine indexes | pgvector 0.8; vectorscale is available if diskann is needed later |
| Schemas `analytics`, `learner_analytics` | C02 | migration `0001` | Empty; C14 (learner caggs) and C22 (owner views, Tiger MCP grants) fill them |
| `POST /v1/sessions` (start voice session: conversation token, dynamic variables, tool token) | C06 | `services/api/src/sg_api/sessions/router.py` | Clerk bearer auth (dev headers only in local/test). Swap `get_briefing_provider` (C09); persist session + `conversation_id` |
| Server-tool auth: `X-SG-Tool-Token`, `require_tool_token`, `check_conversation` | C06 | `services/api/src/sg_api/sessions/tool_tokens.py` | Every `/v1/agent-tools/*` route must use both |
| Server-tool contracts `/v1/agent-tools/{get_briefing, record_observation, fetch_question, run_tests, log_commitment, report_commitment_progress, search_my_documents, query_my_analytics}` | C06 | `agents/tools/*.yaml` (request bodies) | Routes are built by the data owners: C09, C11/C12, C07/C12, C16, C18, C08, C14. `record_observation.dimension` adds `communication`, which is not in `Dimension` (contracts or `sg_core.models.enums`): C10/C11 decide. Persist panel sessions as `character=vidura, mode=panel_interview` |
| Client-tool contracts (`show_question_card`, `highlight_plant`, `open_editor`, `show_diagram`, `focus_plant`, `set_filter`, `scrub_timeline`) | C06 | `agents/tools/*.yaml` | Implemented in the browser by C12, C14, C16 |
| Agent dynamic variables | C06 | `agents/dynamic_variables.yaml` | Set by `POST /v1/sessions`; a test enforces parity |
| `ElevenLabsClient` (conversation token, Voice Design) | C06 | `services/core/src/sg_core/providers/elevenlabs.py` | C03 extends it (usage ledger, budgets) |
| Settings `ELEVENLABS_AGENT_IDS`, `AGENT_TOOL_TOKEN_SECRET`, `ELEVENLABS_BASE_URL` | C06 | `services/core/src/sg_core/settings.py` | `uv run sg-agents ids` prints the agent IDs JSON |
| `sg-agents` CLI (build, sync, test, voices, ids) | C06 | `services/agentops`, `agents/README.md` | |
| Python service image: `SERVICE` build arg (`sg_api`, `sg_worker`, `sg_mcp_gateway`) | C05 | `services/Dockerfile`, `services/docker-entrypoint.sh` | Arguments after the image name replace the default process (e.g. `alembic upgrade head`) |
| Railway config as code | C05 | `infra/railway/*.json` | `api.json` runs `alembic upgrade head` as the pre-deploy step; the worker never migrates |
| Redis client `get_redis()` / `ping()` | C05 | `services/core/src/sg_core/redis_client.py` | `REDIS_URL` is optional (`None` locally); `/readyz` checks Redis only when it is set |
| Settings: `cors_origin_regex`, `git_sha`, optional `redis_url` | C05 | `services/core/src/sg_core/settings.py` | `git_sha` reads `GIT_SHA` or `RAILWAY_GIT_COMMIT_SHA` |
| `GET /healthz` (liveness) and `GET /readyz` (database and Redis) | C05 | `services/api/src/sg_api/routers/health.py` | `/readyz` is the Railway deploy gate |
| `GET /healthz` on web and admin | C05 | `apps/*/src/app/healthz/route.ts` | Public in each app's `proxy.ts`; returns the configured `API_URL` |
| Deploy smoke test | C05 | `scripts/smoke.py`, `python -m sg_worker.smoke` | |

## Log
Newest entries first. One line per merged PR: date, component, PR link, summary.

- 2026-10-04 · C05 · [#5](https://github.com/Virum9520/Project_X/pull/5) · Simple hosting: shared service image, Railway/Vercel config as code, `/readyz` deploy gate with Redis, migrations on deploy, smoke scripts, CI image builds, [hosting runbook](hosting.md).
- 2026-10-04 · C06 · [#8](https://github.com/Virum9520/Project_X/pull/8) · ElevenLabs agents-as-code (8 agents, 15 tools, 14 tests, `sg-agents`), Voice Design prompts, `POST /v1/sessions` with signed tool tokens, spike ADRs 0001–0005. Voices and first sync pending the API key.
- 2026-10-04 · C01 · [#9](https://github.com/Virum9520/Project_X/pull/9) · Clerk identity (JWKS), owner allowlist + MFA, capabilities, CSRF guard and audit middleware, learner onboarding, owner-console gate, and an early landing page (review in C23).
- 2026-10-04 · C02 · [#6](https://github.com/Virum9520/Project_X/pull/6) · DB baseline: Alembic (async), models for all 37 core tables, `session_events`/`usage_events` hypertables, pgvector HNSW indexes, analytics schemas, CI migrations job.
- 2026-10-04 · C00 · Phase 0 foundations: monorepo, Python services, CI, Tiger dev DB connected, coordination docs.
