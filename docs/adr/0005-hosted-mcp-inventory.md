# ADR 0005: ElevenLabs hosted MCP inventory (spike e)

- Status: Proposed
- Date: 2026-10-04
- Component: C06 (research), C22 (implementation)

## Findings
- Endpoint: `https://api.elevenlabs.io/v1/mcp` (Streamable HTTP). Regional variants exist for EU,
  India and Singapore residency.
- Auth: OAuth only. Authorization server `https://api.us.elevenlabs.io`. Scopes:
  `convai_read`, `convai_write`, `text_to_speech`, `speech_history_read`, `flows`,
  `image_video_generation`, `voice_generation`.
- Documented capabilities: list, inspect and compare agents; list recent conversations and read
  transcripts; explore conversation topics; estimate an agent's LLM usage and cost; check
  knowledge-base size; generate short TTS links; and write operations (create, update, duplicate,
  delete agents).
- Exact tool names are not published. They require an authenticated `tools/list` call.
- No subscription, invoice or credit-history tool is documented beyond cost estimation, so
  billing data still comes from the REST API and post-call `charging` metadata.

## Decision (proposed)
- The gateway (C22) requests only `convai_read` and keeps an explicit allow-list of read tools,
  populated from `tools/list` on first connect and reviewed by the owner. Unknown or write tools
  are dropped even if the scope allows them.
- Cost answers come from our usage ledger (C03), labelled estimated, provider-reported or
  reconciled. MCP cost estimates are labelled "estimate".
- Transcripts reached through MCP are data, never instructions, and count as a separate
  capability from usage views.

## Live check (needs owner OAuth)
Connect once from the gateway, save the `tools/list` output to
`services/mcp_gateway/inventory/elevenlabs.json`, and mark each tool read or write.
