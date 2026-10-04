# Security review (C23 part A)

Scope: the API (`services/api`), shared core (`services/core`), the owner-assistant gateway
(`services/mcp_gateway`) and the web/admin apps as they stand after C22. Method: read the code
paths that cross a trust boundary, then pin each conclusion with a test so it stays true.

## Trust boundaries and where each is enforced

| Boundary | Enforcement | Pinned by |
|---|---|---|
| Anonymous to learner routes (`/v1/*`) | Clerk JWT verified via JWKS (`current_session`, `current_learner`) | `test_security_routes.py::test_learner_routes_require_a_session` (sweeps every route in the OpenAPI schema) |
| Learner to owner routes (`/v1/admin/*`) | Owner email allowlist, verified email, MFA, per-route capability | `test_admin_routes_refuse_anonymous_and_learner_tokens`, `..._owner_without_mfa` |
| Cross-site request to owner mutations | `admin_origin_guard` (Origin allowlist) on every non-GET admin route | `test_admin_mutations_refuse_cross_site_requests_even_for_the_owner` |
| Voice agent to API (`/v1/agent-tools/*`) | HMAC session tool token (per user, session, character, expiry); a Clerk token is not accepted and a tool token is not a user session | `test_agent_tools_demand_a_valid_session_tool_token`, `test_a_tool_token_is_not_a_user_session` |
| Provider to API (`/v1/webhooks/*`) | HMAC verification, stored first, idempotent | `test_webhook_route.py`, `test_unknown_webhook_provider_and_unsigned_bodies_are_rejected` |
| Learner A to learner B | Every store query is keyed by the Clerk user id from the verified session, never from the request body | Per-feature tests: `test_accountability_api.py` (other learner's commitments), `test_knowledge_api.py` (documents), `test_garden.py` and `test_garden_db.py` (memories), `test_live_growth.py`, `core/tests/test_knowledge_db.py` (isolation) |
| Uploaded text and transcripts to the model | Treated as data: flagged for injection, kept verbatim, never executed; evidence must quote the learner | `core/tests/test_knowledge_extract.py::test_injection_text_is_flagged_but_kept_verbatim`, C11 validator tests |
| Owner assistant to the database | Dedicated read-only role limited to `analytics.*` views (migration 0004), plus a SQL validator and a tool allowlist in the gateway | `mcp_gateway/tests/test_security.py` (29 write and out-of-scope statements, never reach the server) |
| Tool output to the model | Wrapped in an untrusted-data envelope; an injected instruction cannot widen the tool set | `test_gateway.py::test_injection_in_tool_output_stays_data`, `test_assistant.py::test_prompt_injection_in_tool_output_cannot_widen_the_tool_set`, `test_security.py::test_an_injected_instruction_in_output_cannot_trigger_a_write` |

The route sweep classifies routes from the live OpenAPI schema. A new endpoint that is not under
`/v1/admin`, `/v1/agent-tools` or `/v1`, and not on the explicit public list, fails
`test_every_route_is_classified` until someone reviews it. The public list is `/healthz`,
`/readyz`, `/v1/recap/shared/{token}` (the signed token is the credential) and
`/v1/webhooks/{provider}`.

## Findings fixed in this change (shared code)

1. **Dev identity header could be trusted on a hosted deploy.** `X-Dev-User-Id` let a caller name
   any user, gated only on `ENVIRONMENT in (local, test)`. `ENVIRONMENT` defaults to `local`, so a
   Railway or Vercel deploy that forgot to set it would have accepted the header. Fix:
   `Settings.dev_identity_allowed` is also false whenever a Railway or Vercel platform variable is
   present, and `current_learner` uses it (`sg_core/settings.py`, `sg_api/sessions/identity.py`).
   Tests: `test_dev_identity_header_is_ignored_outside_a_dev_machine`,
   `test_hosted_platform_disables_dev_identity_even_if_environment_is_unset`.
2. **Share tokens were written to the access log.** `RequestContextMiddleware` logged the raw URL
   path, and `/v1/recap/shared/{token}` carries a signed share token (a bearer credential). Fix:
   the access log records the route template (`/v1/recap/shared/{token}`), or `<unmatched>`
   (`sg_api/middleware.py`). Test: `test_access_log_never_contains_share_tokens`.

## Observability and privacy

Sentry and OpenTelemetry are opt-in (`SENTRY_DSN`, `OTEL_EXPORTER_OTLP_ENDPOINT`); unset means no
network calls. Sentry runs with `send_default_pii=False` and a `before_send` scrub. Logs and
error events pass through `sg_core.redaction`, which replaces values under sensitive keys
(authorization, cookie, password, secret, token, api key, signature, DSN) and scrubs emails,
phone numbers, bearer tokens, JWTs and provider keys from free text. Transcripts and document
text are not logged on purpose; the key list is the backstop. Tests: `core/tests/test_observability.py`.

## Residual risks and follow-ups

- **Not exercised live**: no Clerk, Tiger or ElevenLabs keys were available. The sweep uses the
  test Clerk fixtures; the real JWKS path and the real `sg_mcp_readonly` login are unverified.
- **Tiger MCP and ElevenLabs tool names** are assumed (C22). Re-check `tools/list` before launch;
  the allowlist fails closed, so an unknown tool is simply unavailable.
- **Rate limiting** is not applied per learner on the API (only cost budgets in the assistant and
  provider-side limits). Add it before opening signups beyond the hackathon.
- **Cross-learner isolation** relies on each store function taking the user id. A new store
  function that forgets the filter is not caught by the route sweep; review store queries in PRs.
- **Dependency and secret scanning** are not part of CI yet; enable Dependabot and secret
  scanning on the repository.
- **Backups** are described in [tiger-backup-pitr.md](tiger-backup-pitr.md); a restore drill has
  not been run.
