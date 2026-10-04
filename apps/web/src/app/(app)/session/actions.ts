"use server";

import type { SessionStartResponse } from "@sg/contracts";

import { apiSend } from "@/lib/api";
import { requireOnboardedLearner } from "@/lib/session";

/**
 * Server Actions behind the voice stage. Each re-verifies the session and forwards the learner's
 * token; the API derives the learner from it, never from what the browser sends.
 */
export type ActionResult<T> = { ok: true; data: T } | { ok: false; message: string };

const CONCEPT_KEY = /^[a-z0-9_]+(\.[a-z0-9_]+)+$/;
const SESSION_ID = /^[0-9a-f-]{36}$/i;

function failure(status: number, detail: string): { ok: false; message: string } {
  if (status === 0) return { ok: false, message: "The session service is unreachable. Try again." };
  if (status === 401) return { ok: false, message: "Your session expired. Sign in again." };
  if (status === 503) return { ok: false, message: "Voice sessions are not available right now." };
  if (status === 502)
    return { ok: false, message: "The voice provider is unavailable. Try again." };
  return { ok: false, message: detail };
}

export async function startDronaSession(input: {
  concept?: string;
  mode?: "concept_exam" | "teach_back";
}): Promise<ActionResult<SessionStartResponse>> {
  await requireOnboardedLearner();
  const concept = input.concept && CONCEPT_KEY.test(input.concept) ? input.concept : undefined;
  const result = await apiSend<SessionStartResponse>("POST", "/v1/sessions", {
    character: "drona",
    focus_concept_id: concept,
    mode: input.mode === "teach_back" ? "teach_back" : undefined,
  });
  return result.ok ? result : failure(result.status, result.detail);
}

export async function endSession(
  sessionId: string,
  status: "completed" | "interrupted",
): Promise<void> {
  await requireOnboardedLearner();
  if (!SESSION_ID.test(sessionId)) return;
  await apiSend<void>("POST", `/v1/sessions/${sessionId}/end`, { status });
}

export async function bindConversation(sessionId: string, conversationId: string): Promise<void> {
  await requireOnboardedLearner();
  if (!SESSION_ID.test(sessionId) || !conversationId || conversationId.length > 128) return;
  await apiSend<void>("PUT", `/v1/sessions/${sessionId}/conversation`, {
    conversation_id: conversationId,
  });
}
