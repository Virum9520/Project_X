# Garden rules profiles

`profile.yaml` (normal) and `profile.demo.yaml` (compressed clock) configure the deterministic
garden rules engine in `services/core/src/sg_core/rules/`. The engine is pure: it never reads
these files itself; `load_profile("normal" | "demo")` does.

Versioning: every output carries `rule_ver = rules@<engine>+<profile>.<version>`. Changing any
value means bumping `version` here (or `ENGINE_VERSION` for algorithm changes). Old revisions
keep their `rule_ver`; replaying them requires the matching profile version.

## Semantics (engine v1)

- Each concept is a plant; each dimension has an **independent** and an **assisted** track.
  Stage ladder (independent only): explanation reached = SPROUTING, application = INDEPENDENT,
  transfer = TRANSFER, retention = RETAINED. Assisted evidence can only earn ASSISTED (ghost).
- A track is reached at `reach_threshold`; outcome credit comes from `outcome_credit`.
- Distinct problem families only. Transfer needs a family different from application's.
- Retention needs earlier independent learning and a gap of `retention_min_gap_seconds`.
- Time never lowers scores. A plant becomes DUE at `next_review_at` and WILTING after
  `wilt_grace_seconds`; a passed review (independent, new family) advances the interval step, an
  independent miss at review time steps it back.
- Judge uncertainty above `max_uncertainty` grows nothing and is returned in `reassess`.

### Decision: the `communication` dimension (open question from C06)

`record_observation.dimension` may be `communication`, but it is **not** a plant dimension and
the engine never grows a plant from it (`skipped: non_growth_dimension`). Communication is judged
against `cs-core@v1/communication.<behavior>` rubrics for Vidura/panel feedback and stored as
evidence and memories, not as garden growth. C11 should keep storing it (the `evidence_items` and
`assessments` `dimension` columns currently reject it, so either map it to the concept's nearest
growth dimension for the judge or add a migration; the engine takes `dimension` as a string, so
no engine change is needed either way).
