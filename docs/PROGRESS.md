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
| C02 | DB baseline: Alembic, extensions, core tables, hypertables | 1 | C00 | in-progress | `feat/c02-db-baseline` | Baseline `0001` applied to the new Skill Garden Tiger service (the old dev DB holds prototype tables). Awaiting owner validation |
| C03 | Provider adapters (ElevenLabs, OpenRouter, OpenAI, E2B, ObjectStore), usage ledger, budget reservations | 2 | C02 | todo | | |
| C04 | Job infrastructure: Hatchet workflows, idempotency keys, webhook ingestion (HMAC) into `provider_events` | 2 | C02 | todo | | |
| C05 | Simple hosting: Vercel (web, admin), Railway (api, worker, Redis), R2 | 2 | C00 | todo | | Needs the owner's Vercel, Railway and R2 accounts |
| C06 | ElevenLabs agents-as-code, Voice Design voices, conversation-token endpoint, spikes (a)–(e) | 3 | C00 | done | `feat/c06-elevenlabs-agents` | 8 agents, 15 tools, 14 agent tests, `sg-agents` CLI, ADRs 0001–0005. `POST /v1/sessions` works on stubs: dev identity until C01, no session row until C02, stub briefing until C09. **Follow-up (owner, needs `ELEVENLABS_API_KEY`):** `sg-agents voices design`/`create`, set dev `api_base_url` after C05, first `sg-agents sync`, commit registries, ADR live checks |
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

**Ready now** (dependencies met): C02, C05, C07, C13, C15.

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
| `POST /v1/sessions` (start voice session: conversation token, dynamic variables, tool token) | C06 | `services/api/src/sg_api/sessions/router.py` | Swap `current_learner` (C01), `get_briefing_provider` (C09); persist session + `conversation_id` (C02) |
| Server-tool auth: `X-SG-Tool-Token`, `require_tool_token`, `check_conversation` | C06 | `services/api/src/sg_api/sessions/tool_tokens.py` | Every `/v1/agent-tools/*` route must use both |
| Server-tool contracts `/v1/agent-tools/{get_briefing, record_observation, fetch_question, run_tests, log_commitment, report_commitment_progress, search_my_documents, query_my_analytics}` | C06 | `agents/tools/*.yaml` (request bodies) | Routes are built by the data owners: C09, C11/C12, C07/C12, C16, C18, C08, C14. `record_observation.dimension` adds `communication`, which is not in `Dimension` (contracts or `sg_core.models.enums`): C10/C11 decide. Persist panel sessions as `character=vidura, mode=panel_interview` |
| Client-tool contracts (`show_question_card`, `highlight_plant`, `open_editor`, `show_diagram`, `focus_plant`, `set_filter`, `scrub_timeline`) | C06 | `agents/tools/*.yaml` | Implemented in the browser by C12, C14, C16 |
| Agent dynamic variables | C06 | `agents/dynamic_variables.yaml` | Set by `POST /v1/sessions`; a test enforces parity |
| `ElevenLabsClient` (conversation token, Voice Design) | C06 | `services/core/src/sg_core/providers/elevenlabs.py` | C03 extends it (usage ledger, budgets) |
| Settings `ELEVENLABS_AGENT_IDS`, `AGENT_TOOL_TOKEN_SECRET`, `ELEVENLABS_BASE_URL` | C06 | `services/core/src/sg_core/settings.py` | `uv run sg-agents ids` prints the agent IDs JSON |
| `sg-agents` CLI (build, sync, test, voices, ids) | C06 | `services/agentops`, `agents/README.md` | |

## Log
Newest entries first. One line per merged PR: date, component, PR link, summary.

- 2026-10-04 · C06 · [#8](https://github.com/Virum9520/Project_X/pull/8) · ElevenLabs agents-as-code (8 agents, 15 tools, 14 tests, `sg-agents`), Voice Design prompts, `POST /v1/sessions` with signed tool tokens, spike ADRs 0001–0005. Voices and first sync pending the API key.
- 2026-10-04 · C00 · Phase 0 foundations: monorepo, Python services, CI, Tiger dev DB connected, coordination docs.
