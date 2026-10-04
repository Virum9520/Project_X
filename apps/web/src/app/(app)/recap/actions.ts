"use server";

import type { RecapPayload } from "@sg/audio";

import { apiSend } from "@/lib/api";
import { requireOnboardedLearner } from "@/lib/session";

/** Server Actions behind the recap page. Each re-verifies the session; the API scopes by learner. */
export type ActionResult<T> = { ok: true; data: T } | { ok: false; message: string };

const WEEK = /^\d{4}-W\d{2}$/;

function failure(status: number, detail: string): { ok: false; message: string } {
  if (status === 0) return { ok: false, message: "The recap service is unreachable. Try again." };
  if (status === 401) return { ok: false, message: "Your session expired. Sign in again." };
  if (status === 503) return { ok: false, message: "Recaps are not set up on this server yet." };
  return { ok: false, message: detail };
}

export async function generateRecap(force = false): Promise<ActionResult<RecapPayload>> {
  await requireOnboardedLearner();
  const result = await apiSend<RecapPayload>("POST", "/v1/recap/generate", { force });
  return result.ok ? result : failure(result.status, result.detail);
}

export async function shareRecap(week: string): Promise<ActionResult<{ path: string }>> {
  await requireOnboardedLearner();
  if (!WEEK.test(week)) return { ok: false, message: "Unknown week." };
  const result = await apiSend<{ path: string }>("POST", `/v1/recap/${week}/share`);
  return result.ok ? result : failure(result.status, result.detail);
}

export async function unshareRecap(week: string): Promise<ActionResult<null>> {
  await requireOnboardedLearner();
  if (!WEEK.test(week)) return { ok: false, message: "Unknown week." };
  const result = await apiSend<void>("DELETE", `/v1/recap/${week}/share`);
  return result.ok ? { ok: true, data: null } : failure(result.status, result.detail);
}
