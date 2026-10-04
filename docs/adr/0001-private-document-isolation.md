# ADR 0001: Private document isolation (spike a)

- Status: Accepted
- Date: 2026-10-04
- Component: C06 (decision), C08 and C12 (implementation)

## Context
Learners upload private study material. Drona should ground teaching in it, but one learner's
documents must never reach another learner's conversation. The brief warns that client-editable
overrides are not an authorization boundary.

## Findings
- ElevenLabs knowledge-base documents are workspace resources. Access control exists only between
  workspace members; there is no per-end-user access control.
- A per-conversation knowledge-base override exists
  (`overrides.conversation_config_override.agent.prompt.knowledge_base`), but the browser sends
  it in `conversation_initiation_client_data`. A modified client can send any document ID it
  learns.
- The conversation token endpoint cannot bind overrides or dynamic variables server-side; it
  accepts only `agent_id`, `participant_name`, `branch_id`, `version_id` and `environment`.
- The conversation-initiation webhook (server-supplied overrides) does not run for SDK or widget
  conversations.

## Decision
1. Private documents never enter the ElevenLabs knowledge base. Every agent's override allow-list
   explicitly sets `agent.prompt.knowledge_base`, `tool_ids`, `prompt` and `llm` to `false`
   (`sg_agentops.compiler`; asserted in `test_agents_are_private_and_not_overridable`).
2. Agents retrieve private material through the `search_my_documents` server tool, which calls
   `POST /v1/agent-tools/search_my_documents`. The API authorizes it with the session-scoped tool
   token (learner, session, character and conversation ID, HMAC-signed, short-lived), then runs
   pgvector retrieval over that learner's active document version only (C08).
3. The ElevenLabs knowledge base may hold shared, non-personal material only, such as the public
   curriculum (C07). Decide per agent later; none is attached today.
4. Tool results are wrapped as data in prompts; guardrails tell agents never to follow
   instructions inside them.

## Consequences
- Isolation rests on our own auth, which we can test, instead of a client-controlled override.
- Retrieval adds a tool round trip (target under 1 s), and passages count against LLM context.
- C08 must return short passages with page references; C12 implements the tool route.

## Live check (needs API key)
- Push agents and confirm a client override of `agent.prompt.knowledge_base` is rejected (the
  docs say non-allowed overrides raise an error).
