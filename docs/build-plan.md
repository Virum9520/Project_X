# Skill Garden: Build Plan

> The approved build plan. Track progress in [PROGRESS.md](PROGRESS.md), and read [CLAUDE.md](../CLAUDE.md) for the parallel-session protocol.

## Context
Hackathon track: **AI, Actually Intelligent**. Repo: `https://github.com/Virum9520/Project_X.git` (private). `/Users/viru/Desktop/Project_X` contains only `docs/architecture-brief.md`. That brief is the product spec, and it is not yet a git repo.

**Product.** Skill Garden is a voice-first AI coaching platform for US computer science students and job seekers. Each AI character teaches, interviews or holds the learner accountable. All learning is turned into **evidence**. A 3D garden grows only when that evidence shows real skill. Every growth event cites what the learner actually demonstrated.

**USP: the Garden is the learner's analytics dashboard.** It works like a dashboard: real stats panels around a living 3D garden. Clicking any element zooms into it in 3D to show more detail. The **Memory Persistence Engine** powers all of it, so every number, plant and leaf traces back to stored, attributable memory and evidence. It gets the most design and engineering investment of anything in the plan.

**Why it is "Actually Intelligent":**
- Growth is graded with evidence, with a split between independent and assisted performance.
- Memory is attributable to its source.
- Progression is decided by deterministic rules, not by vibes.

We treat it as a production app with no time limit. The priorities are product viability, unique functionality and top-tier 3D UX.

### Locked decisions
| Area | Decision |
|---|---|
| Product | The full Skill Garden brief, plus 4 signature features: Future-Self voice, Retention calls, Living soundscape with Sanjaya recap, Panel interview with Teach-back |
| 3D | Stylized mythic-modern floating-island garden, with stylized VRM characters and real-time lip-sync |
| Accounts on hand | ElevenLabs (paid), Tiger Cloud, OpenRouter, OpenAI. No Twilio and no Anthropic direct account |
| Telephony | **Call channel is pluggable.** We build the **web call channel**: an in-app or PWA "incoming call" over ElevenLabs WebRTC. The phone channel (your relay, Twilio or SIP through ElevenLabs) is an interface and adapter stub only; **not implemented now** |
| Hosting (now) | **Simple managed hosting.** Vercel runs `web` and `admin`. Railway runs `api`, `worker` and Redis. Tiger Cloud is the database, Hatchet Cloud runs jobs, and Cloudflare R2 (S3-compatible) holds files. Locally, everything runs in Docker. No AWS infrastructure yet |
| Hosting (later) | Production AWS (ECS Fargate, set up with Terraform) stays in the plan as the **final phase**. Every adapter is S3- and 12-factor-compatible, so moving there is a config change, not a rewrite |
| Auth | **One Clerk application** shared by `web` and `admin`. Learners sign up freely. Admin access is limited to an allowlist of owner emails (`ADMIN_OWNER_EMAILS`, currently only the project owner's email), checked on the server, with MFA required. FastAPI verifies tokens through JWKS |
| LLM routing | **OpenRouter** for chat and judge models (chosen per task), **OpenAI** for embeddings |

**On your idea of using an ElevenLabs agent for embeddings and building the ER data:** it isn't reliable enough to be the system of record, so I chose option 1.
- ElevenLabs agents don't produce embeddings.
- Their post-call "data collection" is LLM extraction with no transactional guarantees, schema migrations or idempotency.
- It is still useful **as a provisional signal**. Each agent's data-collection fields, such as `concepts_discussed` and `commitment_made`, are fed into the evidence pipeline as hints, and the backend validates them.
- Tiger Data is still the analytics backbone: hypertables, continuous aggregates and pgvector.

---

## Architecture

```
apps/web (learner, Next.js + R3F) ──► ElevenLabs Agents (WebRTC, backend-issued conversation token)
apps/admin (owner console)        │        │ server tools (narrow authed endpoints)
        │                         ▼        ▼
        └──────────────► services/api (FastAPI) ◄── ElevenLabs post-call webhooks (HMAC verified)
                                │
              ┌─────────────────┼──────────────────────┐
              ▼                 ▼                      ▼
       Tiger Cloud PG      Hatchet (durable jobs,     R2/S3 (docs, recordings,
  (Timescale + pgvector)    cron, idempotency)         generated audio)
                                │
                     services/worker (Python): ingestion, judge, rules engine,
                     call dispatcher, recap/music generation, reconciliation
                                │
            OpenRouter · OpenAI embeddings · E2B sandbox · ElevenLabs REST · MCP gateway
```

### Stack
- **Frontend**
  - Next.js (App Router) and TypeScript, Tailwind, shadcn/ui, Framer Motion.
  - R3F v9, drei, `@react-three/postprocessing` on WebGL. WebGPU later, once R3F v10 is stable.
  - `@pixiv/three-vrm`, `@dgreenheck/ez-tree`, `camera-controls`, `detect-gpu` for performance tiers.
  - `@elevenlabs/react`, Monaco editor.
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, Pydantic v2, `uv`.
- **Jobs:** Hatchet, using Hatchet Cloud first with self-hosting on ECS possible later. It provides durable workflows, cron, concurrency keys and retries.
- **Data:** Tiger Cloud Postgres. Hypertables hold usage, session and garden events; continuous aggregates serve analytics; pgvector holds RAG and memory. Cloudflare R2 holds blobs through an S3-compatible `ObjectStore`. Redis (Railway, Upstash later if needed) handles rate limits, locks and caching.
- **Live updates:** server-sent events (SSE) from the API push garden changes to the browser the moment a revision commits.
- **Monorepo:** pnpm + Turborepo for JS and `uv` workspaces for Python. Shared contracts are generated as types from FastAPI OpenAPI with `openapi-typescript`.
- **Infrastructure (now):**
  - Vercel projects for `apps/web` and `apps/admin`, with preview deploys on PRs.
  - Railway services built from Dockerfiles for `api`, `worker` and `mcp_gateway`.
  - GitHub Actions runs CI. Vercel and Railway deploy automatically from `main`.
- **Infrastructure (later, final phase):** Terraform AWS with VPC, ALB, CloudFront, WAF, ECS Fargate, ECR, Secrets Manager and CloudWatch.

### Repo layout
```
apps/web            learner app (garden, sessions, Krishna, Bhima call UI)
apps/admin          owner console (admin.<domain>)
packages/ui         shared design system
packages/three      shared 3D: garden generator, VRM avatar + lipsync, scenes, shaders
packages/contracts  generated API types + zod schemas
services/api        FastAPI (routers: auth, users, sessions, agents-tools, webhooks, garden, admin, calls)
services/worker     Hatchet workflows
services/mcp_gateway  owner-assistant tool gateway (ElevenLabs hosted MCP + Tiger MCP sidecar)
agents/             ElevenLabs agents-as-code (configs, prompts, workflows, tests) via `elevenlabs` CLI
curriculum/         versioned concept catalog YAML (CS core first) + rubrics
infra/             railway.json / vercel.json now; terraform/ (AWS) added in the final phase
scripts/            asset generation (voices, SFX, music), seeding, ops
docs/               architecture-brief.md (existing) + ADRs
```

---

## ElevenLabs usage map

| Capability | Where it's used |
|---|---|
| **Agents and workflows (subagents)** | Phases within each character, e.g. Drona: warm-up, teach, cross-question, teach-back; Arjuna: intro, problem, hint, wrap-up |
| **Voice Design** | One distinct, unique voice per character, generated from prompts and versioned in `agents/voices.json` |
| **Server and client tools** | Server tools: `get_briefing`, `record_observation`, `fetch_question`, `run_tests`, `log_commitment`. Client tools: `show_question_card`, `highlight_plant`, `open_editor`, `show_diagram` |
| **Knowledge base and RAG** | Shared curriculum knowledge base per agent. Private user documents go through backend-authorized retrieval (a server tool), because client overrides are not an authorization boundary. Isolation is decided in a spike |
| **Overrides and dynamic variables** | Bounded session briefing, learner name, due concepts, persona tone |
| **Turn-taking and eagerness** | "Patient" for interviews, "Normal" for Krishna |
| **Post-call webhooks** | `post_call_transcription` and `post_call_audio` start the evidence pipeline, with HMAC verification |
| **Data collection and success evaluation** | Provisional signals plus operational quality checks |
| **Agent testing (simulation and tool-call tests)** | Run in CI with `elevenlabs agents test` |
| **Versioning and traffic splits** | A/B test agent versions; the owner console compares their retry and quality metrics |
| **Instant Voice Cloning + v3/v4 audio tags** | **Future-Self**: Krishna's messages spoken in the learner's own voice |
| **TTS with timestamps** | Sanjaya recap narration. Character alignment drives both lip-sync and camera keyframes |
| **`onAudioAlignment` / output frequency data** | Real-time lip-sync for live agents, with frequency data as fallback |
| **Eleven Music** | Adaptive garden soundscape stems for the moods seedling, thriving, wilting and blooming |
| **Sound Effects** | Growth, bloom, wilt, level-up and call-ring sounds, generated once and cached in S3 |
| **Scribe v2 realtime** | Live captions and think-aloud transcript in Arjuna's code editor. Also used to verify the consent phrase before voice cloning |
| **Multi-voice agent** | Panel interview with Arjuna and Vidura in one session |
| **Hosted MCP (OAuth)** | Owner assistant reads agents, conversations and cost estimates through the gateway |
| **Twilio/SIP outbound (future)** | Phone adapter for Bhima behind the `CallChannel` interface. Stub only |

---

## Domain model (core tables)
- **Identity:** `users`, `profiles`, `admin_users`, `admin_role_grants`, `capabilities`, `audit_log`.
- **Curriculum:** `curricula(version)`, `concepts`, `concept_edges` (prerequisites), `rubrics(version)`.
- **Knowledge:** `documents`, `document_versions(hash, status)`, `chunks(embedding vector)`, `concept_mappings`.
- **Sessions:**
  - `sessions(character, mode, agent_version, el_conversation_id)`
  - `session_events` (hypertable), `provider_events` (raw webhooks, unique on event id)
  - `code_snapshots`, `sandbox_runs`, `hints_given`
- **Evidence and progression:**
  - `evidence_items`
  - `assessments(rev, judge_model, rubric_ver, uncertainty)`
  - `assessment_disputes`, `garden_revisions(rev, rule_ver)`
  - `plant_states(concept, dimension_scores, status: unassessed|sprouting|assisted|independent|transfer|retained|due|wilting)`
- **Memory:** `memories(layer, source, status, expires_at, superseded_by)`. Layers are profile, knowledge, session, skills, commitments and private.
- **Accountability:** `commitments`, `call_schedules(tz, local_time, days, channel, consent_ver)`, `call_occurrences(unique schedule+local_date, state)`, `call_attempts`.
- **Voice identity:** `voice_consents(recording_s3, phrase_verified, voice_id, revoked_at)`.
- **Economics:**
  - `usage_events` (hypertable), `cost_entries(estimated|provider|reconciled)`
  - `budget_reservations`, `shared_allocations`, `pricing_versions`
- **Analytics views:**
  - **Learner analytics:** `learner_analytics.*` continuous aggregates (concept-stage counts per day, dimension scores over time, review backlog, independent vs assisted counts, session minutes). Row-level filtering by `user_id` powers the Garden Dashboard and Sanjaya's tools.
  - **Owner analytics:** read-only `analytics.*` views and continuous aggregates. These are the only objects the Tiger MCP role can read.

**Garden semantics.** Each concept is a plant, and each evidence dimension maps to a plant part:

| Dimension | Plant part |
|---|---|
| Explanation | Roots |
| Application | Stem |
| Transfer | Branches |
| Retention | Blossoms |

- Assisted evidence renders as translucent "ghost growth".
- Overdue reviews make the plant wilt.
- Clicking any part opens the **Evidence Inspector**: quote, timestamp, code run and judge rationale.

---

## USP: Garden Dashboard, powered by the Memory Persistence Engine

### Memory Persistence Engine (the brain)
One backend module, `services/api/memory/` plus worker jobs, owns everything the system knows about a learner.

- **Layers:** profile, knowledge, session, skills, commitments and private reflections, as defined in the brief.
- **Fields on each memory:** `source`, `evidence_refs`, `status` (provisional/accepted/superseded/disputed), `confidence`, `expires_at`, `superseded_by`.
- **Writes are append-only.** Corrections create new revisions, so the full history can be replayed.
- **Read paths:**
  1. **Session briefing builder:** a bounded, relevance-ranked set of memories (pgvector similarity, recency and due-ness) sent to ElevenLabs as dynamic variables.
  2. **Garden projection:** the deterministic rules engine turns accepted evidence into `plant_states` and `garden_revisions`.
  3. **Analytics projection:** Tiger hypertables and continuous aggregates of memory and evidence events, giving per-concept, per-domain and per-dimension time series. These feed the dashboard stats.
- **User-facing memory controls,** inside the dashboard zoom view:
  - See what each character remembers about you and why.
  - Correct it, or delete private items.
  - Each change shows exactly which plants or stats it affects.
- **ElevenLabs integration:**
  - Agents read memory through the `get_briefing` server tool.
  - Agents propose memory through `record_observation` and `log_commitment`.
  - Proposals enter as provisional and are promoted only through the evidence pipeline.

### Garden Dashboard layout (`apps/web/app/garden`)
A **dashboard-first** screen. The 3D garden is the central visual, surrounded by real analytics; it is not a game screen with stats bolted on.

- **Center:** the 3D floating-island garden. Each domain (DSA, OS, networks, databases, system design, behavioral) is a **grove**; each concept is a **plant**.
- **Left rail: KPIs.**
  - **Readiness score** for the target role, computed from the job description or goal and broken down by domain.
  - Concepts by stage: unassessed, sprouting, assisted, independent, transfer, retained.
  - **Independent-to-assisted ratio.**
  - Reviews due and overdue (wilting count).
  - Streak, and hours practised this week.
- **Right rail: Insights.**
  - Sanjaya's "what changed and why" feed with evidence citations.
  - Top misconceptions.
  - The "next best practice" card, which launches the right character in one click.
- **Bottom: timeline.**
  - Growth over time (stacked area by stage, from a Tiger continuous aggregate).
  - Session history as scrubbable markers.
  - **Time-travel scrubber:** drag to replay the garden at any past revision, possible because revisions are append-only.
- **Filters:** domain, dimension, character, date range, and a toggle between independent-only and all evidence. The 3D scene and the stats re-filter together; unmatched plants dim.

### Semantic 3D zoom: click to drill in
The camera flies smoothly with `camera-controls`. The stats rails **change context** at each level.

| Level | 3D view | Stats panel shows |
|---|---|---|
| **Garden** | Whole island, grove clusters, glowing prerequisite roots | Overall readiness, stage distribution, weekly trend |
| **Grove** (domain) | Zoom to a cluster; plants are labeled and the health aura is visible | Domain readiness, weakest concepts, prerequisite gaps, domain timeline |
| **Plant** (concept) | Close-up. Roots = explanation, stem = application, branches = transfer, blossoms = retention. Ghost and translucent parts are assisted; wilting means a review is due | Per-dimension scores and history, next review date, misconceptions, memory items about this concept, "Practise with Drona/Arjuna" |
| **Part** (evidence) | Macro zoom on one root, branch or blossom; floating evidence cards orbit it | The exact transcript quote, code snapshot and test results, judge rationale and uncertainty, rubric version, and "Dispute this" |

- **Keyboard and accessibility:** Esc zooms out a level and arrow keys move between siblings. A synced 2D table view is always available.
- **Voice navigation ("Ask Sanjaya").** A Sanjaya ElevenLabs agent sits on the dashboard with server tools that query **only this learner's** analytics views, plus client tools such as `focus_plant`, `set_filter` and `scrub_timeline`.
  - Example: "Which graph topics am I weakest at?" The camera flies to the Graphs grove, the panels filter, and Sanjaya explains with citations.
- **Live updates:** SSE pushes provisional growth during a session. The dashboard glows and animates the changed plant even when it is open in another tab.

### Fast, visible progression (built for the demo, still evidence-backed)
Growth has to show up **during and within seconds of** a session, not after days of practice.

1. **Live growth during the call.**
   - When the learner answers a question, Drona calls the server tool `record_observation`.
   - A **fast provisional micro-judge** grades that single answer in about 2–4 s, using a small, quick OpenRouter model and the concept rubric.
   - The plant immediately sprouts or grows a part as **glowing provisional growth**, pushed over SSE with a sound effect.
   - The learner sees the garden respond in real time while they talk.
2. **Confirmation within seconds of hanging up.**
   - The post-call workflow runs right away, without batching.
   - The full judge pass confirms or adjusts each provisional growth: glow solidifies into real growth, or gently retracts with an explanation.
   - Target: under 30 s from call end to confirmed garden revision.
3. **Generous, fast default thresholds**, kept in versioned `rules/profile.yaml`:

   | Evidence | Growth |
   |---|---|
   | 1 good independent explanation | Roots, and the plant visibly sprouts |
   | 1 independent solve | Stem |
   | 1 solve in a different problem family | Branches |
   | 1 later correct recall | Blossoms |

   Every stage is reachable in a single 5–10 minute session (Teach-back plus 2 problems).
4. **Demo profile.**
   - `rules/profile.demo.yaml` uses a **compressed spaced-repetition clock**: reviews fall due in minutes, not days.
   - So wilting and retention calls can be shown live.
   - Enabled per account (demo and test accounts only). The owner console marks it clearly. It is never mixed with real learner analytics.
5. **Seeded demo learner.** Pre-built history (a half-grown garden, a few wilting plants due for review), so the demo opens on a rich scene. One live session then visibly changes it.
6. **Integrity is kept.**
   - Provisional growth is visually distinct and stored as provisional.
   - Only confirmed assessments create permanent garden revisions.
   - Every plant part still cites its evidence.

---

## Step-by-step build phases
Each phase ends with a working, deployed vertical slice and its acceptance checks.

### Phase 0: Repo and foundations
1. `git init`, add the remote `origin` → `Virum9520/Project_X`, `main` branch with branch protection, `.gitignore`, `.editorconfig`, MIT or proprietary license (to choose), README.
2. Scaffold the monorepo: pnpm, Turbo, `uv`, the two Next.js apps, FastAPI, the worker, and the packages.
3. Local dev with `docker-compose`:
   - `timescale/timescaledb-ha` (pgvector included)
   - Redis
   - LocalStack S3
   - Hatchet Lite
4. Tooling: ESLint, Prettier, Ruff, mypy and pyright, Vitest, pytest, Playwright, pre-commit. CI in GitHub Actions runs lint, typecheck, test and the contract-drift check.
5. `.env.example` files, settings validated with pydantic-settings, and a secrets convention.

### Phase 1: Identity, RBAC and contracts
1. One Clerk application for both apps. Learner sign-up is open, with onboarding (major, goals, experience, timezone).
2. Admin access:
   - Granted only to emails in `ADMIN_OWNER_EMAILS` (bootstrapped from deployment configuration), with MFA required.
   - Anyone else who signs in to `apps/admin` is refused by the server.
   - More admins can be added later through capability grants, never through profile edits.
3. FastAPI verifies the JWT with JWKS. Admin endpoints also require the allowlist and capability checks.
4. Capability-based permissions, an audit-log middleware recording actor, action, target, request ID and before/after state, and CSRF checks for admin mutations.
5. Alembic baseline migration for all core tables. Generate OpenAPI and contracts.

### Phase 2: Platform core and simple hosting
1. Provider adapters with one interface, each writing to the usage ledger:
   - `ElevenLabsClient`, `LLMClient` (OpenRouter), `EmbeddingClient` (OpenAI)
   - `SandboxClient` (E2B), `ObjectStore` (S3-compatible: R2 now, MinIO locally, AWS S3 later)
2. Usage ledger and budget reservations:
   - Atomic reserve and settle, with `SELECT … FOR UPDATE`.
   - Per-user monthly allowance; the US$5–10 target is configurable.
3. Webhook ingestion:
   - Verify HMAC, store raw `provider_events` with a unique constraint, acknowledge fast, enqueue a Hatchet workflow.
4. Hatchet worker skeleton with idempotency keys and a dead-letter view.
5. Simple hosting:
   - Vercel for `web` and `admin`; Railway for `api`, `worker` and Redis.
   - Tiger Cloud connection over TLS, Hatchet Cloud, and an R2 bucket.
   - Secrets kept in Vercel and Railway environment variables.
   - Automatic deploy from `main`. Health-check endpoint and a smoke script.

### Phase 3: ElevenLabs spike and agents-as-code
1. `agents/` managed with the `elevenlabs` CLI: prompts as markdown, workflows, tool definitions and tests, all versioned in git.
2. Use Voice Design to create the 7 voices (Drona, Arjuna, Vidura, Bhima, Krishna, Sanjaya, owner-assistant) and save the voice IDs.
3. `POST /sessions` builds a bounded briefing and returns a **conversation token**, with dynamic variables and session ID.
4. **Spikes, with written ADRs:**
   - (a) Knowledge-base isolation for private documents.
   - (b) Multi-voice panel feasibility.
   - (c) `onAudioAlignment` timing quality for lip-sync.
   - (d) Webhook payload completeness for evidence reconciliation.
   - (e) Hosted MCP tool inventory.
5. Agent simulation tests run in CI.

### Phase 4: Curriculum and knowledge pipeline
1. `curriculum/cs-core@v1`, about 80 concepts:
   - DSA, complexity, OS, networking, databases, system design and behavioral competencies.
   - Prerequisite edges and per-concept rubrics.
2. Document upload: S3 → hash and version → text extraction with page references (PyMuPDF, with OCR fallback).
3. LLM concept-mapping proposal, validated against the catalog → chunks → OpenAI embeddings → pgvector.
4. Activate a new document version only after indexing succeeds. Keep the previous version on failure. Pin each session to the document version it used.
5. Treat document text as untrusted data. Prompts wrap it, and tools never execute instructions found in documents.

### Phase 5: Drona loop end-to-end (the core proof)
1. Session UI: voice stage with Drona's avatar, question cards, live captions and a provisional evidence ticker.
2. Drona's workflow: warm-up → teach → cross-question → **Teach-back mode**. Drona plays a confused student and the learner must explain the concept, which produces the strongest explanation evidence.
3. Post-call pipeline as a Hatchet workflow:
   1. Ingest the transcript and reconcile it with question IDs and tool events.
   2. Assemble evidence.
   3. Run objective checks.
   4. **One judge pass** through OpenRouter with structured output: concept, dimension, outcome, evidence references, rationale, uncertainty.
   5. Validate schema, ownership and references.
   6. Apply the versioned rules engine to produce a garden revision.
   7. Commit in a single transaction with an outbox event.
4. Rules engine:
   - Pure Python, deterministic and versioned.
   - Separates assisted from independent evidence; only distinct problem families count.
   - Ambiguous evidence triggers a reassessment flag.
5. Live provisional growth through `record_observation` and the micro-judge, with SSE garden updates during the call. See "Fast, visible progression".
6. Sanjaya report: what changed, why (with citations), and what to practise next.
7. Memory update and briefing for the next session (unresolved gaps). The user can correct memories.
8. A minimal garden view (a simple R3F plant per concept) so the loop can be demoed. Phase 6 replaces it with the full scene.
9. Interrupted sessions produce partial evidence. Replaying the same assessment produces an identical garden; duplicate webhooks don't award growth twice.

### Phase 6: Garden Dashboard, the USP (top-tier UI)
This phase gets the most polish. See "USP: Garden Dashboard" above for the full spec.
1. **Analytics API backed by the Memory Engine** (`/garden/*`):
   - Summary KPIs, per-grove and per-plant stats, and evidence detail.
   - Timeline series from Tiger continuous aggregates; garden state at any revision for time travel.
   - A readiness-score model: versioned, explainable, with weighted dimensions per target role.
   - All endpoints return citations and data freshness.
2. **Dashboard shell:**
   - Responsive layout with a KPI rail, insights rail and timeline. Charts in Visx or Recharts, matched to the garden's theme.
   - Filters synced to the URL, so any zoomed view can be linked to.
   - Stats rails change context with the zoom level.
3. **3D scene:**
   - Floating mythic island: stylized terrain, water, god-rays, fireflies, bloom, depth of field, and day-night tied to the learner's local time.
   - Garden generator: garden state becomes deterministic seeded plants (ez-tree for groves, custom L-system shader plants for concepts, instanced foliage). Growth animates between revisions. Prerequisites shown as glowing root paths.
4. **Semantic zoom:** Garden → Grove → Plant → Part.
   - Camera choreography with `camera-controls`, a level-of-detail swap at each level, and evidence cards orbiting at Part level.
   - Keyboard navigation, plus a synced 2D table view for accessibility.
5. **Memory panel:** see, correct and delete memories, with an impact preview showing which plants and stats change.
6. **Time-travel scrubber**, and **Ask Sanjaya** voice navigation (an ElevenLabs agent with learner-scoped analytics tools and camera and filter client tools).
7. VRM characters:
   - Stylized avatars, one per character, made in VRoid and customized, with Mixamo idle, talk and gesture clips retargeted.
   - Lip-sync pipeline: `onAudioAlignment` characters → phonemes → VRM visemes (`aa/ih/ou/ee/oh`), blinking and saccades. Frequency-data fallback.
8. Performance tiers chosen with `detect-gpu`:
   - Low: no postprocessing, fewer instances.
   - High: full effects.
   - Plus lazy-loaded assets, KTX2/Draco compression, and a frame budget at 60fps on an M1 or mid-tier laptop.

### Phase 7: Arjuna technical interview
1. Parse the résumé or job description into an interview plan; résumé claims stay self-reported.
2. Problem bank with problem families and hidden tests. Monaco editor in the voice stage.
3. **E2B sandbox:**
   - Server tool `run_tests`.
   - Limits on network, time and memory.
   - Results stored as evidence.
4. Code snapshots are streamed to the agent with `sendContextualUpdate`. Hints are tracked as `assisted`. Scribe realtime provides think-aloud captions.

### Phase 8: Vidura HR and Panel interview
1. Behavioral questions using STAR rubrics for communication behaviors: structure, specificity, ownership, conciseness.
2. Optional camera **delivery** observations computed in the browser with MediaPipe: framing, gaze toward camera, and speaking pace from transcript timing.
   - These never infer honesty, personality or competence.
   - Frames are sampled, and nothing is uploaded unless the learner opts in.
3. **Panel interview:** Arjuna and Vidura in one session, multi-voice, both avatars on stage with turn-aware camera cuts. Built according to the Phase 3 spike result.

### Phase 9: Bhima accountability and Retention calls
1. Commitments CRUD, with self-reported and verified completion kept separate.
2. Scheduling:
   - IANA timezone, local time and days.
   - DST rules: skip non-existent times and run ambiguous ones once.
   - Unique occurrence key per schedule and local date.
   - Hatchet cron creates occurrences.
3. Dispatcher state machine:
   - Steps: reserve budget and slot → recheck consent, quiet hours and cancellation → dispatch through the `CallChannel`.
   - States: queued, dispatching, ringing, connected, completed, unanswered, missed, failed, cancelled, unknown.
4. **`WebCallChannel` (implemented):**
   - Web Push (PWA service worker) shows an "Incoming call from Bhima" screen.
   - Accepting starts an ElevenLabs WebRTC session with a capped duration and graceful wrap-up.
   - Unanswered calls time out and become missed; no auto-redial.
5. **`PhoneCallChannel` (interface and stub only):** adapter shape for your relay, Twilio or SIP through the ElevenLabs outbound API. It records the conversation ID and Call SID. Not implemented.
6. **Retention calls:**
   - Each call ends with one spaced-repetition question on a concept that is due.
   - The answer goes through the judge and becomes retention evidence, so blossoms bloom or the plant wilts.
   - Habit completion never counts as technical evidence.

### Phase 10: Krishna and Future-Self voice
1. Krishna morning session in an energetic or calm tone. Private reflections are stored only if the user opts in, with configurable sharing across characters.
2. **Future-Self voice:**
   - Explicit consent screen.
   - The learner records a scripted consent phrase live in the app; Scribe verifies the phrase matches. This blocks uploading someone else's audio.
   - Then Instant Voice Clone, with the `voice_id` stored per user.
3. Daily "message from your future self": an LLM-written script from the learner's goals and recent wins, spoken with v3/v4 audio tags in their own voice.
4. One-tap revoke deletes the voice at ElevenLabs and in our database. The cloned voice is used for this feature only.

### Phase 11: Living soundscape and Sanjaya recap
1. `scripts/generate-audio`:
   - Eleven Music loopable stems per mood and season.
   - SFX library for growth, bloom, wilt, ring and UI sounds.
   - Uploaded to S3 and versioned.
2. Client audio engine: crossfade stems by garden health and time of day, with spatial SFX on plants and mute and volume controls.
3. **Weekly Sanjaya recap** job:
   - Accepted assessments → narrative script with citations → TTS with timestamps.
   - **Camera keyframes timed to the moment each concept is spoken**, with Sanjaya on screen and lip-synced.
   - Playable cinematic flythrough, shareable as a private link.

### Phase 12: Owner Console
1. Six pages: Overview, Users, Usage and costs, Calls, Quality and ops, Ask the assistant. Readable tables and charts in Tremor/Recharts style.
2. **Call now:**
   - Idempotent request ID, cooldown and cost estimate.
   - Calls go to an approved developer test target over the web channel; the phone channel comes later.
   - Test-tagged records with a separate developer budget.
3. **Owner assistant:**
   - An OpenRouter model with tool use → `mcp_gateway`, which applies auth, a tool allowlist, row, time and size limits, and audit logging.
   - The gateway connects to the ElevenLabs hosted MCP (OAuth, read-only tools) and the Tiger MCP sidecar (dedicated read-only role on `analytics.*` views only).
   - Answers state date range, metric definitions, freshness, and whether figures are estimated or reconciled.
   - Optional voice mode with an owner-assistant agent.
4. Reconciliation jobs: ElevenLabs conversation cost metadata becomes cost entries, and estimated entries are replaced by reconciled ones. Plus month-end projection.

### Phase 13: Hardening and demo (on simple hosting)
1. Observability on the current hosting: Sentry, OpenTelemetry and log redaction (PII). Tiger backups and point-in-time recovery (PITR).
2. Security review:
   - Admin endpoints reject learner tokens.
   - User isolation tests and prompt-injection tests on uploaded documents.
   - Gateway write rejection.
3. Load tests with k6: API, worker backlog and database connections. Voice concurrency measured against plan limits. 3D frame-time budgets.
4. Judge calibration set of human-labeled answers; track the disagreement rate in Quality.
5. Demo seed data, a scripted 3-minute demo path, landing page, and pitch assets.

### Phase 14 (later): Production AWS migration
1. `infra/terraform`:
   - VPC, ALB, CloudFront and WAF.
   - ECS Fargate services: web, admin, api, worker, mcp-gateway.
   - ECR, Secrets Manager, CloudWatch alarms and dashboards, autoscaling.
   - S3 replaces R2 as a config change.
2. GitHub Actions deploys through OIDC, with dev and prod environments. Private connectivity to Tiger Cloud.
3. Optionally self-host Hatchet on ECS.
4. Cutover runbook, then load tests repeated on AWS.

---

## Verification (applies throughout)
- **Unit tests:**
  - Rules engine with property tests: replay is deterministic and duplicates are no-ops.
  - Budget reservation races, DST scheduling edge cases, webhook HMAC, the call state machine.
- **Integration tests** (pytest + testcontainers Timescale):
  - The full post-call pipeline with recorded ElevenLabs webhook fixtures, producing a garden revision.
  - Interrupted and duplicate webhooks.
- **Agents:** `elevenlabs agents test` simulation and tool-call tests for each character in CI.
- **End-to-end (Playwright):**
  - Onboarding → upload document → start a Drona session (mocked ElevenLabs in CI, real in a manual smoke test) → garden updates → Evidence Inspector shows the citation.
  - Admin login with MFA; Call now hitting a test browser session.
- **Manual smoke test on the deployed dev environment (Vercel + Railway) each phase:** a real voice session, real webhook, real garden growth, and a web call that rings.
- **Demo-speed checks:**
  - Provisional growth appears within 5 s of an answer.
  - Confirmed revision lands within 30 s of the call ending.
  - A fresh concept reaches blossom in one demo session under the demo profile.
- **Visual and performance checks:** Playwright screenshots of key 3D scenes, and an FPS check at each performance tier.
- **Dashboard correctness:**
  - Every KPI and plant part reconciles to its source evidence rows (test: sum of stage counts equals plants; each part has at least one evidence reference).
  - Time travel to revision N matches a replay of the rules engine up to N.
  - A memory correction updates the affected plants and stats after recompute.
  - Zoom levels are reachable by mouse, keyboard and Ask Sanjaya.

## Open items to confirm during build
- **Telephony.** "Relay" was read as your existing telephony relay (or SIP). The phone adapter stays a stub until you share its API.
- **Panel interview.** Whether multi-voice works in one agent depends on the Phase 3 spike. The fallback is two linked agents handing off through the workflow.
- **Domain name, license, and initial cohort/concurrency.** These are needed for final sizing in Phase 13.
