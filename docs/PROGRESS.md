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
| C01 | Identity and RBAC: Clerk (one app), JWKS verification, admin allowlist plus MFA, capabilities, audit log | 1 | C00, C02 | in-progress | `feat/c01-identity` | Built ahead of C02 behind interfaces: `GrantStore` (grants nothing yet) and `AuditSink` (logs) get DB-backed versions once `admin_role_grants` / `audit_log` exist. Onboarding answers live in Clerk `publicMetadata.onboarding` until `profiles` exists |
| C02 | DB baseline: Alembic, extensions, core tables, hypertables | 1 | C00 | todo | | Most backend components wait on this |
| C03 | Provider adapters (ElevenLabs, OpenRouter, OpenAI, E2B, ObjectStore), usage ledger, budget reservations | 2 | C02 | todo | | |
| C04 | Job infrastructure: Hatchet workflows, idempotency keys, webhook ingestion (HMAC) into `provider_events` | 2 | C02 | todo | | |
| C05 | Simple hosting: Vercel (web, admin), Railway (api, worker, Redis), R2 | 2 | C00 | todo | | Needs the owner's Vercel, Railway and R2 accounts |
| C06 | ElevenLabs agents-as-code, Voice Design voices, conversation-token endpoint, spikes (a)–(e) | 3 | C00 | todo | | The token endpoint needs C01; the rest can start now |
| C07 | Curriculum `cs-core@v1` (about 80 concepts, prerequisite edges, rubrics) as YAML plus a loader | 4 | none | todo | | Content-only and ready to start |
| C08 | Knowledge ingestion pipeline (upload, extract, map, embed, activate) | 4 | C02, C03, C04, C07 | todo | | |
| C09 | Memory Persistence Engine: append-only memories, briefing builder, projections | 5–6 | C02 | todo | | Core USP backend |
| C10 | Rules engine: deterministic, versioned, `profile.yaml` and `profile.demo.yaml` | 5 | C07 | todo | | Pure Python, can start on mocks |
| C11 | Evidence and judge pipeline: post-call workflow, micro-judge, validation, garden revisions | 5 | C03, C04, C09, C10 | todo | | |
| C12 | Drona session loop: voice stage UI, server and client tools, Teach-back, live provisional growth over SSE | 5 | C01, C06, C11 | todo | | UI can start on mocks |
| C13 | 3D garden scene and generator in `packages/three` (island, plants, growth animation, semantic zoom) | 6 | C00 | todo | | Ready to start; uses mock garden state |
| C14 | Garden Dashboard: analytics API, dashboard shell, KPI and insights rails, timeline, time travel, memory panel, Ask Sanjaya | 6 | C09, C10, C13 | todo | | USP. UI can start on mocks |
| C15 | VRM avatars and lip-sync (`onAudioAlignment` to visemes) | 6 | C00 | todo | | Ready to start |
| C16 | Arjuna technical interview: résumé and job description parsing, problem bank, Monaco, E2B tests, Scribe captions | 7 | C11, C12 | todo | | |
| C17 | Vidura HR interview and Panel interview | 8 | C12 | todo | | |
| C18 | Bhima accountability: commitments, scheduler, dispatcher, `WebCallChannel`, retention calls | 9 | C01, C03, C04, C06 | todo | | `PhoneCallChannel` is a stub only |
| C19 | Krishna and Future-Self voice (consent checked with Scribe, IVC, revoke) | 10 | C01, C03, C06 | todo | | |
| C20 | Living soundscape (Music and SFX asset script, audio engine) and Sanjaya weekly recap | 11 | C03 (assets), C11 and C13 (recap) | todo | | The asset script can start once C03 is done |
| C21 | Owner Console: 6 pages, Call now | 12 | C01, C03 | todo | | |
| C22 | MCP gateway and owner assistant (ElevenLabs hosted MCP, Tiger MCP read-only) | 12 | C21 | todo | | |
| C23 | Hardening and demo: observability, security review, load tests, judge calibration, demo seed | 13 | most | todo | | |
| C24 | Production AWS migration (Terraform, ECS) | 14 | C23 | todo | | Later |

**Ready now** (dependencies met): C02, C05, C06 (except the token endpoint), C07, C13, C15.

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

## Log
Newest entries first. One line per merged PR: date, component, PR link, summary.

- 2026-10-04 · C00 · Phase 0 foundations: monorepo, Python services, CI, Tiger dev DB connected, coordination docs.
