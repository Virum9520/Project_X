# ADR 0004: Post-call webhook completeness for evidence (spike d)

- Status: Accepted, live check pending
- Date: 2026-10-04
- Component: C06 (decision), C04 (ingestion), C11 (evidence)

## Context
The evidence pipeline must reconcile each conversation with question IDs, answers, tool calls,
assistance, cost and timing, and must never award growth twice.

## Findings: what `post_call_transcription` carries
| Need | Field | Notes |
|---|---|---|
| Correlate to our session | `data.conversation_id` | Returned by the token endpoint before the call; POST /v1/sessions records it |
| Who | `data.user_id` | Only if the client sent `userId`; client-supplied, so never trusted |
| Per-turn transcript | `data.transcript[] {role, message, time_in_call_secs}` | Quotes for evidence citations |
| Tool calls and results | `transcript[].tool_calls[] {tool_name, params_as_json}`, `tool_results[] {result_value, is_error}` | Contains every `record_observation` with question IDs and assistance |
| Workflow phase | `transcript[].agent_metadata.workflow_node_id` | Distinguishes teach-back explanations from cross-questions |
| Panel speaker | `transcript[].multivoice_message.parts[].voice_label` | See ADR 0002 |
| Provisional signals | `analysis.data_collection_results`, `analysis.evaluation_criteria_results` | Hints only; never authoritative |
| Cost | `metadata.cost` (credits), `metadata.charging {llm_charge, call_charge, ...}`, `metadata.call_duration_secs` | Feeds the usage ledger (C03) |
| Session context | `conversation_initiation_client_data.dynamic_variables` | `secret__` values arrive redacted |
| Integrity | `ElevenLabs-Signature: t=...,v0=HMAC_SHA256(secret, "{t}.{body}")` | Reject if older than 30 minutes; compare with `hmac.compare_digest` |

Retries are opt-in and only for `post_call_transcription` (up to 5 attempts, 30 s to 30 min) with
identical payloads. `post_call_audio` carries only the base64 MP3.

## Decision
- Authority for learner identity is our session row (C02), keyed by the `conversation_id` that
  POST /v1/sessions received with the token. Webhook `user_id` and dynamic variables are ignored
  for authorization.
- `record_observation` tool calls in the transcript are the primary evidence spine. Each must
  match a live tool-call record stored by the tool endpoint; the webhook copy is used to reconcile
  missed or duplicate calls.
- C04 stores raw events in `provider_events` unique on `(provider, conversation_id, type)`,
  verifies the signature before parsing, returns 200 fast and enqueues the workflow. Enable
  webhook retries.
- Missing webhooks are reconciled by `GET /v1/convai/conversations/{id}` on a schedule.

## Live check (needs API key and a deployed webhook URL)
Record one real payload per character into `services/api/tests/fixtures/elevenlabs/` (redacted),
and confirm every field in the table is present, especially `workflow_node_id`, tool calls and
`charging`.
