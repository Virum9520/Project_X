"use server";

import type { AssistantAnswer, AssistantTurn } from "@sg/contracts";

import { apiPost } from "@/lib/api";
import { requireOwner } from "@/lib/owner";

export type AskState =
  { status: "ok"; answer: AssistantAnswer } | { status: "error"; message: string };

const MAX_QUESTION = 2000;

/**
 * Server action behind the assistant box. It re-checks the owner session, then posts to the API,
 * which repeats the owner-only, MFA and capability checks, audits the question, and has the
 * gateway audit every tool call. Nothing here talks to a provider or sees a credential.
 */
export async function askAssistant(question: string, history: AssistantTurn[]): Promise<AskState> {
  await requireOwner();
  const text = question.trim();
  if (!text) return { status: "error", message: "Type a question first." };
  if (text.length > MAX_QUESTION) {
    return { status: "error", message: `Keep questions under ${MAX_QUESTION} characters.` };
  }
  const result = await apiPost<AssistantAnswer>("/v1/admin/assistant/ask", {
    question: text,
    history: history.slice(-12),
  });
  if (!result.ok) {
    const message =
      result.status === 429
        ? "The assistant is busy with other questions. Try again in a moment."
        : result.status === 503
          ? `The assistant is not available: ${result.detail}`
          : result.detail;
    return { status: "error", message };
  }
  return { status: "ok", answer: result.data };
}
