# Curriculum

Versioned concept catalogs. Each concept is a plant in the garden and each domain is a grove.
The backend loads a version into `curricula`, `concepts`, `concept_edges` and `rubrics`
(see `sg_core.curriculum`).

```bash
uv run python -m sg_core.curriculum validate              # cs-core v1 by default
uv run python -m sg_core.curriculum load --activate       # sync into DATABASE_URL
```

## Layout

```
<key>/<version>/
  curriculum.yaml             key, version, title, rubric_version, domains, assessment_guardrails
  concepts/<domain>.yaml      one file per grove: `domain:` plus `concepts:`
  rubrics/dimensions.yaml     generic outcome levels for explanation, application, transfer, retention
  rubrics/communication.yaml  communication behaviors scored in behavioral answers
```

## Concept fields

| Field | Notes |
|---|---|
| `key` | `<domain>.<slug>`. **Stable across versions**: learner history follows the key |
| `title`, `summary` | Shown in the garden and in agent briefings |
| `topic` | Sub-cluster inside the grove (layout and filtering) |
| `difficulty` | 1 (first-year) to 5 (hard interview topic) |
| `aliases` | Other names, used when mapping documents and transcripts to concepts |
| `prerequisites` | **Direct** prerequisites only (an edge implied by another is rejected). Cross-grove edges are fine. No cycles |
| `related` | Non-prerequisite links. Declare each pair once |
| `rubric` | `explanation` (2 or more), `application`, `transfer` criteria and known `misconceptions`. Retention re-checks explanation and application after a review interval |

## Rules

- `validate` must pass, and `pnpm format:check` covers these files (Prettier).
- Once a version is **active** it is immutable, because evidence cites its concepts and rubrics.
  Change content by adding a new version directory (for example `cs-core/v2`).
  A **draft** version can be edited and re-synced in place.
- Rubric criteria describe observable evidence. The `assessment_guardrails` in `curriculum.yaml`
  go into every judge prompt.
