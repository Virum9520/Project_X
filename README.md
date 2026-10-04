# Skill Garden

Voice-first AI coaching for CS students and job seekers. Mentors teach, interview and hold you
accountable; every learning moment becomes **evidence**, and a living 3D garden — your analytics
dashboard — grows only from what you actually demonstrate.

Hackathon track: **AI — Actually Intelligent**. Product spec: [docs/architecture-brief.md](docs/architecture-brief.md).

## Repository layout

| Path | What lives there |
| --- | --- |
| `apps/web` | Learner app (Next.js 16, React Three Fiber garden dashboard, voice sessions) |
| `apps/admin` | Owner console (invite-only, MFA) |
| `packages/contracts` | Shared domain types; generated API types land here |
| `packages/ui` | Design tokens and shared components |
| `packages/three` | Shared 3D: garden generator, avatars, lip-sync |
| `packages/tsconfig` | Shared TypeScript configs |
| `services/core` | `sg_core`: settings, logging, database, provider adapters |
| `services/api` | `sg_api`: FastAPI HTTP API |
| `services/worker` | `sg_worker`: Hatchet durable jobs (ingestion, judge, rules, calls) |
| `services/mcp_gateway` | Owner-assistant tool gateway |
| `agents/` | ElevenLabs agents-as-code |
| `curriculum/` | Versioned concept catalog and rubrics |

## Prerequisites

- Node 22+ and pnpm (`npm i -g --prefix ~/.local pnpm` if global installs need root)
- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 automatically)
- A Postgres with TimescaleDB + pgvector: a Tiger Cloud dev service, or `docker compose up db`

## Getting started

```bash
cp .env.example .env              # fill in DATABASE_URL and provider keys
pnpm install
uv sync --all-packages

pnpm dev                          # web on :3000, admin on :3001
uv run --package sg_api uvicorn sg_api.main:app --reload --port 8000
uv run --package sg_worker python -m sg_worker.main   # embedded Hatchet locally
```

## Quality gates

```bash
pnpm lint && pnpm typecheck && pnpm build && pnpm format:check
uv run ruff check services && uv run ruff format --check services
uv run mypy services/core/src services/api/src services/worker/src services/mcp_gateway/src
uv run pytest -q
```

CI runs the same checks on every pull request (`.github/workflows/ci.yml`).

## Hosting

Now: Vercel (`web`, `admin`) + Railway (`api`, `worker`, Redis) + Tiger Cloud + Hatchet Cloud +
Cloudflare R2. Later: AWS ECS Fargate via Terraform. Python services share `services/Dockerfile`.
