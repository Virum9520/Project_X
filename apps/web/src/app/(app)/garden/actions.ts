"use server";

import type { AskSanjayaAnswer, MemoryItem } from "@sg/contracts";

import { apiSend } from "@/lib/api";
import { currentLearnerOrNull } from "@/lib/session";

/**
 * Server Actions behind the memory panel and Ask Sanjaya. Each re-verifies the session (Server
 * Actions are public endpoints) and forwards the learner's token; the API scopes every call to
 * that learner, so ids from the browser are never trusted on their own.
 */
export type ActionResult<T> = { ok: true; data: T } | { ok: false; message: string };

const SIGNED_OUT = { ok: false, message: "Sign in to do that." } as const;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function failure(status: number, detail: string): { ok: false; message: string } {
  if (status === 0) return { ok: false, message: "The garden service is unreachable. Try again." };
  if (status === 401) return { ok: false, message: "Your session expired. Sign in again." };
  if (status === 404) return { ok: false, message: "That memory no longer exists." };
  return { ok: false, message: detail };
}

export async function correctMemory(
  memoryId: string,
  content: string,
): Promise<ActionResult<MemoryItem>> {
  if (!(await currentLearnerOrNull())) return SIGNED_OUT;
  const text = content.trim();
  if (!UUID.test(memoryId) || !text) return { ok: false, message: "Nothing to save." };
  const result = await apiSend<MemoryItem>("POST", `/v1/garden/memories/${memoryId}/correct`, {
    content: text,
  });
  return result.ok ? result : failure(result.status, result.detail);
}

export async function deleteMemory(memoryId: string): Promise<ActionResult<null>> {
  if (!(await currentLearnerOrNull())) return SIGNED_OUT;
  if (!UUID.test(memoryId)) return { ok: false, message: "Unknown memory." };
  const result = await apiSend<void>("DELETE", `/v1/garden/memories/${memoryId}`);
  return result.ok ? { ok: true, data: null } : failure(result.status, result.detail);
}

export async function askSanjaya(question: string): Promise<ActionResult<AskSanjayaAnswer>> {
  if (!(await currentLearnerOrNull())) return SIGNED_OUT;
  const text = question.trim().slice(0, 500);
  if (!text) return { ok: false, message: "Ask a question first." };
  const result = await apiSend<AskSanjayaAnswer>("POST", "/v1/garden/ask", { question: text });
  return result.ok ? result : failure(result.status, result.detail);
}
