# Architecture decision records

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-private-document-isolation.md) | Private documents: backend-authorized retrieval, never the ElevenLabs knowledge base | Accepted |
| [0002](0002-panel-interview-multi-voice.md) | Panel interview: one multi-voice agent; agent transfer as fallback | Accepted, live check pending |
| [0003](0003-lip-sync-audio-alignment.md) | Lip-sync from `onAudioAlignment` over WebRTC; frequency data fallback | Accepted, live check pending |
| [0004](0004-post-call-webhook-completeness.md) | Post-call webhook carries what the evidence pipeline needs; we correlate by our own session record | Accepted, live check pending |
| [0005](0005-hosted-mcp-inventory.md) | Hosted MCP: read-only `convai_read`, inventory by `tools/list` at connect time | Proposed |

Spikes (a)–(e) from build-plan Phase 3 were researched on 2026-10-04 against the ElevenLabs
OpenAPI spec embedded in `@elevenlabs/cli` 1.4.0, `@elevenlabs/client` 1.26.0,
`elevenlabs-python` 2.70.0 and the ElevenLabs docs. Items marked "live check" need an API key and
are listed at the end of each ADR.
