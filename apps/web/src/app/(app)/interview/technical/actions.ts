"use server";

import type {
  AgentRun,
  ArjunaSessionStart,
  EditorLanguage,
  ProblemView,
  RunExamplesResult,
  RunnableLanguage,
  SnapshotAck,
} from "@sg/contracts";

import { apiGet, apiSend } from "@/lib/api";
import { asRunnable } from "@/lib/arjuna/language";
import { requireOnboardedLearner } from "@/lib/session";

/**
 * Server Actions behind the Arjuna interview. Each re-verifies the session and forwards the
 * learner's token; the API derives the learner from it and scopes every row to them.
 */
export type ActionResult<T> = { ok: true; data: T } | { ok: false; message: string };

const CONCEPT_KEY = /^[a-z0-9_]+(\.[a-z0-9_]+)+$/;
const SESSION_ID = /^[0-9a-f-]{36}$/i;
const PROBLEM_ID = /^p_[a-z0-9_]{1,60}$/;
const EDITOR_LANGUAGES: readonly string[] = [
  "python",
  "javascript",
  "typescript",
  "java",
  "cpp",
  "go",
];
const MAX_CODE = 50_000;

function failure(status: number, detail: string): { ok: false; message: string } {
  if (status === 0)
    return { ok: false, message: "The interview service is unreachable. Try again." };
  if (status === 401) return { ok: false, message: "Your session expired. Sign in again." };
  if (status === 429) return { ok: false, message: "Too many runs. Wait a moment and try again." };
  if (status === 503) return { ok: false, message: detail || "This is not available right now." };
  if (status === 502)
    return { ok: false, message: "The voice provider is unavailable. Try again." };
  return { ok: false, message: detail };
}

export async function startArjunaSession(input: {
  language: RunnableLanguage;
  concept?: string;
}): Promise<ActionResult<ArjunaSessionStart>> {
  await requireOnboardedLearner();
  const result = await apiSend<ArjunaSessionStart>("POST", "/v1/arjuna/sessions", {
    language: asRunnable(input.language),
    focus_concept_id: input.concept && CONCEPT_KEY.test(input.concept) ? input.concept : undefined,
  });
  return result.ok ? result : failure(result.status, result.detail);
}

export async function getProblem(
  problemId: string,
  language: EditorLanguage,
): Promise<ActionResult<ProblemView>> {
  await requireOnboardedLearner();
  if (!PROBLEM_ID.test(problemId) || !EDITOR_LANGUAGES.includes(language))
    return { ok: false, message: "That problem is not available." };
  const result = await apiGet<ProblemView>(
    `/v1/arjuna/problems/${problemId}?language=${encodeURIComponent(language)}`,
  );
  return result.ok ? result : failure(result.status, result.detail);
}

export async function saveCode(input: {
  sessionId: string;
  problemId: string;
  language: EditorLanguage;
  code: string;
  trigger?: "autosave" | "run" | "submit";
}): Promise<ActionResult<SnapshotAck>> {
  await requireOnboardedLearner();
  if (!SESSION_ID.test(input.sessionId) || !PROBLEM_ID.test(input.problemId))
    return { ok: false, message: "Unknown session or problem." };
  if (!EDITOR_LANGUAGES.includes(input.language) || input.code.length > MAX_CODE)
    return { ok: false, message: "That code cannot be saved." };
  const result = await apiSend<SnapshotAck>("PUT", `/v1/arjuna/sessions/${input.sessionId}/code`, {
    problem_id: input.problemId,
    language: input.language,
    code: input.code,
    trigger: input.trigger ?? "autosave",
  });
  return result.ok ? result : failure(result.status, result.detail);
}

export async function runExamples(input: {
  sessionId: string;
  problemId: string;
  language: RunnableLanguage;
  code: string;
}): Promise<ActionResult<RunExamplesResult>> {
  await requireOnboardedLearner();
  if (!SESSION_ID.test(input.sessionId) || !PROBLEM_ID.test(input.problemId))
    return { ok: false, message: "Unknown session or problem." };
  if (!input.code.trim() || input.code.length > MAX_CODE)
    return { ok: false, message: "Write some code first." };
  const result = await apiSend<RunExamplesResult>(
    "POST",
    `/v1/arjuna/sessions/${input.sessionId}/run-examples`,
    {
      problem_id: input.problemId,
      language: asRunnable(input.language),
      code: input.code,
    },
  );
  return result.ok ? result : failure(result.status, result.detail);
}

export async function listRuns(sessionId: string, after?: string): Promise<AgentRun[]> {
  await requireOnboardedLearner();
  if (!SESSION_ID.test(sessionId)) return [];
  const query = after ? `?after=${encodeURIComponent(after)}` : "";
  const result = await apiGet<AgentRun[]>(`/v1/arjuna/sessions/${sessionId}/runs${query}`);
  return result.ok ? result.data : [];
}

export async function getScribeToken(): Promise<ActionResult<{ token: string; model_id: string }>> {
  await requireOnboardedLearner();
  const result = await apiSend<{ token: string; model_id: string }>(
    "POST",
    "/v1/arjuna/scribe-token",
  );
  return result.ok ? result : failure(result.status, result.detail);
}
