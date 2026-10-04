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
| C01 | Identity and RBAC: Clerk (one app), JWKS verification, admin allowlist plus MFA, capabilities, audit log | 1 | C00, C02 | todo | | Owner allowlist comes from `ADMIN_OWNER_EMAILS` |
| C02 | DB baseline: Alembic, extensions, core tables, hypertables | 1 | C00 | done | `feat/c02-db-baseline` | Baseline `0001` is applied to the dedicated Skill Garden Tiger service. The old dev DB holds prototype tables, so point `DATABASE_URL` at the new service |
| C03 | Provider adapters (ElevenLabs, OpenRouter, OpenAI, E2B, ObjectStore), usage ledger, budget reservations | 2 | C02 | todo | | |
| C04 | Job infrastructure: Hatchet workflows, idempotency keys, webhook ingestion (HMAC) into `provider_events` | 2 | C02 | todo | | |
| C05 | Simple hosting: Vercel (web, admin), Railway (api, worker, Redis), R2 | 2 | C00 | todo | | Needs the owner's Vercel, Railway and R2 accounts |
| C06 | ElevenLabs agents-as-code, Voice Design voices, conversation-token endpoint, spikes (a)–(e) | 3 | C00 | claimed | `feat/c06-elevenlabs-agents` | The token endpoint needs C01; the rest can start now |
| C07 | Curriculum `cs-core@v1` (about 80 concepts, prerequisite edges, rubrics) as YAML plus a loader | 4 | none | todo | | Content-only and ready to start |
| C08 | Knowledge ingestion pipeline (upload, extract, map, embed, activate) | 4 | C02, C03, C04, C07 | todo | | |
| C09 | Memory Persistence Engine: append-only memories, briefing builder, projections | 5–6 | C02 | todo | | Core USP backend |
| C10 | Rules engine: deterministic, versioned, `profile.yaml` and `profile.demo.yaml` | 5 | C07 | todo | | Pure Python, can start on mocks |
| C11 | Evidence and judge pipeline: post-call workflow, micro-judge, validation, garden revisions | 5 | C03, C04, C09, C10 | todo | | |
| C12 | Drona session loop: voice stage UI, server and client tools, Teach-back, live provisional growth over SSE | 5 | C01, C06, C11 | todo | | UI can start on mocks |
| C13 | 3D garden scene and generator in `packages/three` (island, plants, growth animation, semantic zoom) | 6 | C00 | done | `feat/c13-3d-garden-scene` | Built on mock garden state; dev showcase at `/lab/garden`. C14 swaps the mock for the analytics API |
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

**Ready now** (dependencies met): C01, C03, C04, C05, C06 (except the token endpoint), C07, C09, C15. C14's UI can now start on the C13 scene and mocks.

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
| SQLAlchemy models for all 37 core tables (`Base`, `HYPERTABLES`, `EMBEDDING_DIM`=1536) | C02 | `services/core/src/sg_core/models/` | One module per domain: identity, curriculum, knowledge, sessions, evidence, memory, accountability, economics. Table semantics are owned by the component named in each module docstring |
| Python domain enums (`Character`, `Dimension`, `PlantStatus`, `MemoryLayer`, `CallState`, …) | C02 | `services/core/src/sg_core/models/enums.py` | Stored as VARCHAR(40) + named CHECK `ck_<table>_<column>`. Adding a value needs a migration that recreates the CHECK. `Character`/`PlantStatus` mirror `packages/contracts` (a test enforces it) |
| Alembic (async, URL from `get_settings()`) | C02 | `alembic.ini`, `services/core/migrations/` | Baseline revision `0001`. Run from the repo root |
| Hypertables `session_events`, `usage_events` | C02 | migration `0001` | Partitioned on `occurred_at`, 7-day chunks, PK `(id, occurred_at)`. No FKs may point at them. `usage_events` dedupes on `(idempotency_key, occurred_at)` |
| Vector columns `chunks.embedding`, `memories.embedding` | C02 | `vector(1536)`, HNSW cosine indexes | pgvector 0.8; vectorscale is available if diskann is needed later |
| Schemas `analytics`, `learner_analytics` | C02 | migration `0001` | Empty; C14 (learner caggs) and C22 (owner views, Tiger MCP grants) fill them |
| Garden snapshot read model (`GardenSnapshot`, `PlantSnapshot`, `DimensionScore`, `PrerequisiteEdge`, `PLANT_STATUSES`) | C13 | `packages/contracts/src/index.ts` | What the scene renders. C14's `/garden/*` API should serve this shape; every curriculum concept is listed, unassessed ones included. `PLANT_STATUSES` mirrors Python `PlantStatus` (test-enforced) |
| Garden generator, growth mapping, semantic-zoom navigation | C13 | `@sg/three` (pure TS, server-safe) | `generateGardenLayout` (deterministic, placement ignores scores), `plantGrowth` (dimension → part; solid/assisted ghost/provisional), `GardenFocus` + `zoomOut`/`zoomIn`/`moveSibling`, URL form via `focusToString`/`focusFromString` (`grove:dsa`, `plant:dsa.graphs`, `part:dsa.graphs:roots`) |
| `GardenScene` React component | C13 | `@sg/three/scene` (client-only) | Load with `next/dynamic(..., { ssr: false })` from a `'use client'` file. Props: `snapshot`, controlled `focus`/`onFocusChange`, `matchedConceptIds` (filter dimming), `pulseConceptIds` (live SSE glow), `evidence(conceptId, part)` + `onEvidenceSelect`, `timeOfDay`, `quality`, `keyboard` |
| Mock garden data | C13 | `@sg/three` (`mockGardenSnapshot`, `mockGardenHistory`, `mockEvidence`, `withProvisionalGrowth`) | Seeded demo learner over 16 revisions with every status. Mock concept ids are illustrative; C07 owns the real curriculum |

## Log
Newest entries first. One line per merged PR: date, component, PR link, summary.

- 2026-10-04 · C13 · PR_LINK · 3D garden scene in `packages/three`: deterministic garden generator, shader-grown concept plants (roots/stem/branches/blossoms, assisted ghost growth, live provisional glow, wilting), floating island with pond, grass, ez-tree elder trees, glowing prerequisite roots, day-night, bloom and depth of field, Garden → Grove → Plant → Part camera zoom with keyboard navigation and orbiting evidence cards, mock garden data, `/lab/garden` showcase.

- 2026-10-04 · C02 · [#6](https://github.com/Virum9520/Project_X/pull/6) · DB baseline: Alembic (async), models for all 37 core tables, `session_events`/`usage_events` hypertables, pgvector HNSW indexes, analytics schemas, CI migrations job.
- 2026-10-04 · C00 · Phase 0 foundations: monorepo, Python services, CI, Tiger dev DB connected, coordination docs.
