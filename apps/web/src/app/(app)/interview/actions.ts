"use server";

import type { SessionStartResponse } from "@sg/contracts";

import { apiSend } from "@/lib/api";
import type { DeliverySummary } from "@/lib/interview/delivery";
import { requireOnboardedLearner } from "@/lib/session";

/**
 * Server Actions behind the interview stage (Vidura HR interview and the Panel). Each
 * re-verifies the session; the API derives the learner from the forwarded token.
 */
export type ActionResult<T> = { ok: true; data: T } | { ok: false; message: string };

const SESSION_ID = /^[0-9a-f-]{36}$/i;

export async function startInterviewSession(input: {
  mode: "hr" | "panel";
}): Promise<ActionResult<SessionStartResponse>> {
  await requireOnboardedLearner();
  const result = await apiSend<SessionStartResponse>("POST", "/v1/sessions", {
    character: input.mode === "panel" ? "panel" : "vidura",
  });
  if (result.ok) return result;
  if (result.status === 0)
    return { ok: false, message: "The session service is unreachable. Try again." };
  if (result.status === 401) return { ok: false, message: "Your session expired. Sign in again." };
  if (result.status === 503)
    return { ok: false, message: "Voice sessions are not available right now." };
  if (result.status === 502)
    return { ok: false, message: "The voice provider is unavailable. Try again." };
  return { ok: false, message: result.detail };
}

/** Opt-in only: three aggregate numbers computed in the browser. Never frames or images. */
export async function sendDeliverySummary(
  sessionId: string,
  summary: DeliverySummary,
): Promise<void> {
  await requireOnboardedLearner();
  if (!SESSION_ID.test(sessionId) || summary.consent !== true) return;
  const body: DeliverySummary = {
    consent: true,
    duration_s: Number(summary.duration_s),
    samples: Number(summary.samples),
    framing_ratio: Number(summary.framing_ratio),
    gaze_ratio: Number(summary.gaze_ratio),
    pace_wpm: summary.pace_wpm === null ? null : Number(summary.pace_wpm),
  };
  await apiSend<void>("POST", `/v1/sessions/${sessionId}/delivery`, body);
}
