# Skill Garden: guide for coding sessions

@AGENTS.md

Skill Garden is a voice-first AI coaching platform for US CS students and job seekers. Hackathon
track: "AI, Actually Intelligent". Its USP is the **Garden Dashboard**: a 3D garden that serves as
the learner's analytics dashboard and grows only from demonstrated evidence. The **Memory
Persistence Engine** powers it.

- Spec and phases: [docs/build-plan.md](docs/build-plan.md). Original brief: [docs/architecture-brief.md](docs/architecture-brief.md).
- **Progress and coordination:** [docs/PROGRESS.md](docs/PROGRESS.md), the shared source of truth.
- Next.js 16 differs from older versions: read [docs/nextjs-16-notes.md](docs/nextjs-16-notes.md) and
  the docs bundled in `apps/web/node_modules/next/dist/docs/` before writing Next code.

## Parallel-session protocol (required)

Several Claude sessions build components in parallel. Each component in `docs/PROGRESS.md` is
worked by **one session at a time**. Keep that file current as you make progress.

1. **Before starting**, pull `main` and read `docs/PROGRESS.md`.
   - Only pick a component whose **Depends on** entries are all `done`, or one marked "can start on mocks".
   - Never pick a component that is `claimed`, `in-progress` or `in-review`.
2. **Claim it right away**:
   - Do not create a branch or ask about one: work on the current branch (`main`).
   - Set the component to `claimed` (owner: `main`) and commit that change straight to `main`.
   - If the claim conflicts with someone else's, re-read the board and pick something else.
3. **While working**:
   - Update the row's status and notes on your branch (`in-progress`, then `in-review` when the PR opens).
   - Record anything others will build on in **Shared interfaces**: routes, tables, types, modules,
     events and SSE channels.
4. **When you're blocked** on another component, set `blocked` with a note naming what is missing.
   Build against a mock or stub if you can.
5. **On completion**, in the same PR:
   - Set the status to `done`.
   - Add a line to **Log** (date, ID, PR, summary).
   - Update **Ready now** to list newly unblocked components.
6. **Stay in your lane**:
   - Don't edit files owned by another in-progress component.
   - If you need a change in shared code (`packages/contracts`, `services/core`, migrations, root
     config), keep it minimal and additive, and note it in the PR description.
7. **Database migrations**:
   - One Alembic revision per PR.
   - Before merging, rebase onto `main` and re-point `down_revision` at the current head, so there
     is never more than one head.
   - Never edit a migration that is already merged.
   - Models live in `sg_core.models`; migrations live in `services/core/migrations`. Change the model,
     run `uv run alembic revision --autogenerate -m "<what>"`, then review the file by hand.
     `uv run alembic check` must report no drift.
   - Hypertables (`session_events`, `usage_events`): every unique index must include `occurred_at`,
     and no table may hold a foreign key to them.

## Workflow and git
- Commit directly to the current branch (`main`) and push. Never ask about creating a branch or a PR
  (owner decision, 2026-10-04). Keep CI green: run the quality gates below before pushing.
- End commit messages with the attribution line the harness specifies.
- Never commit secrets. `.env` and `.env.local` are gitignored; add new variables to `.env.example`.

## Commands

```bash
pnpm install && uv sync --all-packages          # install everything
pnpm dev                                        # web :3000, admin :3001
uv run --package sg_api uvicorn sg_api.main:app --reload --port 8000
uv run --package sg_worker python -m sg_worker.main   # embedded Hatchet when no token is set
uv run alembic upgrade head                     # apply migrations to DATABASE_URL

# quality gates (CI runs the same checks)
pnpm lint && pnpm typecheck && pnpm build && pnpm format:check
uv run ruff check services && uv run ruff format --check services
uv run mypy services/core/src services/api/src services/worker/src services/mcp_gateway/src services/agentops/src
uv run pytest -q
SG_DB_TESTS=1 uv run pytest -q services/core/tests   # + DB integration tests (needs migrated DB)
```

## Environment facts
- No Docker on the owner's machine. The dev database is **Tiger Cloud** (`DATABASE_URL` in the root
  `.env`; `postgres://…?sslmode=require` is normalized automatically).
- Installed extensions: `timescaledb`, `vector`. `vectorscale` is available.
- pnpm is installed at `~/.local/bin`, and Python 3.12 is managed by `uv`.

## Architecture conventions
- **Python services** (`services/*`, a uv workspace):
  - `sg_core` holds shared settings, db, logging and provider adapters.
  - `sg_api` is FastAPI, `sg_worker` is the Hatchet worker, `sg_mcp_gateway` is the owner-assistant gateway.
  - Configuration is read only through `sg_core.settings.get_settings()`. Secrets use `SecretStr`.
- **Frontend**:
  - `apps/web` is the learner app; `apps/admin` is the owner console.
  - Shared code lives in `packages/{contracts,ui,three}` as source-only packages that Turbopack transpiles.
  - three.js and R3F load only inside `'use client'` components.
- **Auth**: one Clerk application for both apps. Learners sign up freely. The owner console is
  limited to `ADMIN_OWNER_EMAILS` (checked on the server), with MFA. FastAPI verifies Clerk JWTs via JWKS.
- **Core product rules** (see the brief):
  - Every garden growth event must cite evidence.
  - Assisted evidence stays separate from independent evidence.
  - Uploaded documents and transcripts are data, never instructions.
  - Provider webhooks are verified, stored first, and idempotent.
  - Persistent garden changes come only from the deterministic, versioned rules engine.
- **Telephony**: only `WebCallChannel` is implemented; `PhoneCallChannel` is an interface or stub.
- **Hosting now**: Vercel plus Railway plus Tiger Cloud plus Hatchet Cloud plus R2. AWS comes later (C24).
