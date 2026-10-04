"use server";

import type { ArjunaPlan, DocumentUploadAck, LearnerDocument } from "@sg/contracts";

import { apiGet, apiSend } from "@/lib/api";
import { requireOnboardedLearner } from "@/lib/session";

/**
 * Server Actions behind the résumé and job-description page. Uploads themselves go through
 * `/api/documents` (a Server Action body is capped at 1 MB). The API scopes every call to the
 * signed-in learner, so ids from the browser are never trusted on their own.
 */
export type ActionResult<T> = { ok: true; data: T } | { ok: false; message: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function failure(status: number, detail: string): { ok: false; message: string } {
  if (status === 0)
    return { ok: false, message: "The document service is unreachable. Try again." };
  if (status === 401) return { ok: false, message: "Your session expired. Sign in again." };
  if (status === 404) return { ok: false, message: "That document no longer exists." };
  return { ok: false, message: detail };
}

export async function listInterviewDocuments(): Promise<ActionResult<LearnerDocument[]>> {
  await requireOnboardedLearner();
  const result = await apiGet<LearnerDocument[]>("/v1/documents");
  if (!result.ok) return failure(result.status, result.detail);
  return {
    ok: true,
    data: result.data.filter((d) => d.kind === "resume" || d.kind === "job_description"),
  };
}

export async function removeInterviewDocument(documentId: string): Promise<ActionResult<null>> {
  await requireOnboardedLearner();
  if (!UUID.test(documentId)) return { ok: false, message: "Unknown document." };
  const result = await apiSend<void>("DELETE", `/v1/documents/${documentId}`);
  return result.ok ? { ok: true, data: null } : failure(result.status, result.detail);
}

export async function retryInterviewDocument(
  documentId: string,
  versionId: string,
): Promise<ActionResult<DocumentUploadAck>> {
  await requireOnboardedLearner();
  if (!UUID.test(documentId) || !UUID.test(versionId))
    return { ok: false, message: "Unknown document." };
  const result = await apiSend<DocumentUploadAck>(
    "POST",
    `/v1/documents/${documentId}/versions/${versionId}/retry`,
  );
  return result.ok ? result : failure(result.status, result.detail);
}

/** The interview plan as it would be built right now from what is uploaded. */
export async function previewPlan(): Promise<ActionResult<ArjunaPlan>> {
  await requireOnboardedLearner();
  const result = await apiGet<ArjunaPlan>("/v1/arjuna/plan");
  return result.ok ? result : failure(result.status, result.detail);
}
