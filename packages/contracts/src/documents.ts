/**
 * Learner documents (C08) as the résumé and job-description upload UI sees them: wire types for
 * `/v1/documents` (snake_case, mirroring `services/api/src/sg_api/knowledge/router.py`).
 * Only the two kinds that feed the interview plan are uploadable from the browser.
 */
export const INTERVIEW_DOCUMENT_KINDS = ["resume", "job_description"] as const;
export type InterviewDocumentKind = (typeof INTERVIEW_DOCUMENT_KINDS)[number];

export type DocumentVersionStatus =
  "uploaded" | "extracting" | "mapping" | "embedding" | "active" | "failed" | "superseded";

export interface DocumentVersion {
  id: string;
  version: number;
  status: DocumentVersionStatus;
  page_count: number | null;
  byte_size: number | null;
  original_filename: string | null;
  extraction_flags: Record<string, unknown>;
  error: string | null;
  created_at: string;
  activated_at: string | null;
}

export interface LearnerDocument {
  id: string;
  title: string;
  kind: "study_material" | InterviewDocumentKind | "other";
  created_at: string;
  active_version_id: string | null;
  versions: DocumentVersion[];
}

export interface DocumentUploadAck {
  document_id: string;
  version_id: string;
  version: number;
  status: DocumentVersionStatus;
  duplicate: boolean;
}
