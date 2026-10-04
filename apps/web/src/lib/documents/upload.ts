import type { DocumentVersion, InterviewDocumentKind, LearnerDocument } from "@sg/contracts";
import { INTERVIEW_DOCUMENT_KINDS } from "@sg/contracts";

/**
 * Browser uploads are capped at 10 MiB (the API allows more): Next buffers at most that much of a
 * request body that passes through `src/proxy.ts`. A résumé or job description is far smaller.
 */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
/** Types C08 can extract. */
export const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"] as const;
export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.join(",");

export const KIND_LABELS: Record<InterviewDocumentKind, string> = {
  resume: "Résumé",
  job_description: "Job description",
};

export const isInterviewKind = (value: unknown): value is InterviewDocumentKind =>
  typeof value === "string" && (INTERVIEW_DOCUMENT_KINDS as readonly string[]).includes(value);

/** Client-side pre-check so an obviously bad file never leaves the browser. */
export function validateUpload(file: { name: string; size: number }): string | null {
  const name = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext)))
    return `Use a ${ACCEPTED_EXTENSIONS.join(", ")} file.`;
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_UPLOAD_BYTES)
    return `That file is larger than ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB.`;
  return null;
}

const PROCESSING = new Set(["uploaded", "extracting", "mapping", "embedding"]);

export const isProcessing = (v: DocumentVersion | undefined): boolean =>
  v !== undefined && PROCESSING.has(v.status);

/** The newest version that is not superseded (the one the learner just uploaded, or the live one). */
export function currentVersion(doc: LearnerDocument): DocumentVersion | undefined {
  return [...doc.versions]
    .filter((v) => v.status !== "superseded")
    .sort((a, b) => b.version - a.version)[0];
}

/** The learner's newest live document of a kind, which is what the interview plan reads. */
export function documentOfKind(
  docs: LearnerDocument[],
  kind: InterviewDocumentKind,
): LearnerDocument | undefined {
  return [...docs]
    .filter((d) => d.kind === kind)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
}

export function statusLabel(v: DocumentVersion | undefined): string {
  switch (v?.status) {
    case undefined:
      return "Not uploaded";
    case "uploaded":
      return "Queued";
    case "extracting":
      return "Reading the file";
    case "mapping":
      return "Finding topics";
    case "embedding":
      return "Finishing up";
    case "active":
      return "Ready";
    case "failed":
      return "Could not be processed";
    case "superseded":
      return "Replaced";
  }
}

/** Plain-language notes for extraction flags that matter to the learner. */
export function flagNotes(flags: Record<string, unknown>): string[] {
  const notes: string[] = [];
  if (flags.needs_ocr)
    notes.push("This looks like a scanned PDF with no text. Upload a text-based copy.");
  if (flags.empty) notes.push("No text could be read from this file.");
  if (flags.truncated) notes.push("Only the first part of this file was read.");
  if (flags.suspected_injection)
    notes.push(
      "This file contains text that looks like instructions. It is treated as plain data and never followed.",
    );
  return notes;
}
