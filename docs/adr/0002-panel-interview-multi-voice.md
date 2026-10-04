# ADR 0002: Panel interview with two voices (spike b)

- Status: Accepted, live check pending
- Date: 2026-10-04
- Component: C06 (decision and prototype agent), C17 (product)

## Context
The Panel interview puts Arjuna (technical) and Vidura (behavioural) in one session with both
avatars on stage and turn-aware camera cuts.

## Options
| Option | How | Pros | Cons |
|---|---|---|---|
| A. Multi-voice agent | `tts.supported_voices` with labels; the LLM wraps lines in `<Arjuna>...</Arjuna>` | One conversation, natural banter, transcript keeps `multivoice_message.parts[].voice_label` | One LLM plays both roles; tag discipline depends on the prompt |
| B. Workflow subagents | `override_agent` nodes with their own voice and prompt | Separate prompts per interviewer | Only one node is active at a time, so quick back-and-forth is clumsy |
| C. `transfer_to_agent` | Two agents hand off | Fully separate agents | Handoffs are slow and one-way; analysis settings stay the parent's |

## Findings
- Multi-voice supports up to 10 voices including the default. Tags are case-sensitive, cannot
  nest, and unknown labels fall back to the default voice.
- Post-call transcripts include per-part voice labels, so evidence can be attributed to the right
  interviewer.
- Clients cannot change `supported_voices` (no override is enabled), so the panel is fixed
  server-side.

## Decision
Option A. `agents/characters/panel` is the prototype: Vidura is the default voice, Arjuna is a
supported voice, and the prompt requires tags for Arjuna's lines. The `voice_tags` agent test and
the `voice_tags_consistent` evaluation criterion check the behaviour. Fallback is option C if tag
discipline fails in live testing.

## Consequences
- C17 drives camera cuts from the speaking voice label. The label is in the transcript; for live
  cuts, C17 checks whether `agent_response` events carry voice labels (live check below) or
  parses tags from the response text.
- C11 attributes panel evidence by voice label: Arjuna lines to application/transfer, Vidura
  lines to communication.

## Live check (needs API key and designed voices)
1. `uv run sg-agents sync`, then `pnpm exec elevenlabs agents test <panel agent id>`.
2. Run three manual panel sessions; confirm voices switch on tags and no tag text is spoken.
3. Inspect one `post_call_transcription` payload for `multivoice_message.parts`.
4. Check whether live `agent_response` client events include the voice label.
