import type { DocumentVersion, LearnerDocument } from "@sg/contracts";
import { describe, expect, it } from "vitest";

import { asRunnable } from "@/lib/arjuna/language";

import {
  MAX_UPLOAD_BYTES,
  currentVersion,
  documentOfKind,
  flagNotes,
  isInterviewKind,
  isProcessing,
  statusLabel,
  validateUpload,
} from "./upload";

const version = (n: number, status: DocumentVersion["status"]): DocumentVersion => ({
  id: `v${n}`,
  version: n,
  status,
  page_count: 1,
  byte_size: 10,
  original_filename: "cv.pdf",
  extraction_flags: {},
  error: null,
  created_at: "2026-10-01T00:00:00Z",
  activated_at: null,
});

const doc = (
  id: string,
  kind: LearnerDocument["kind"],
  created: string,
  versions: DocumentVersion[],
): LearnerDocument => ({
  id,
  title: id,
  kind,
  created_at: created,
  active_version_id: null,
  versions,
});

describe("validateUpload", () => {
  it("accepts supported types case-insensitively", () => {
    expect(validateUpload({ name: "CV.PDF", size: 1000 })).toBeNull();
    expect(validateUpload({ name: "jd.docx", size: 1000 })).toBeNull();
    expect(validateUpload({ name: "notes.md", size: 1000 })).toBeNull();
  });
  it("rejects other types, empty files and oversized files", () => {
    expect(validateUpload({ name: "cv.exe", size: 1000 })).toMatch(/Use a/);
    expect(validateUpload({ name: "cv.pdf.exe", size: 1000 })).toMatch(/Use a/);
    expect(validateUpload({ name: "cv.pdf", size: 0 })).toMatch(/empty/);
    expect(validateUpload({ name: "cv.pdf", size: MAX_UPLOAD_BYTES + 1 })).toMatch(/larger/);
    expect(validateUpload({ name: "cv.pdf", size: MAX_UPLOAD_BYTES })).toBeNull();
  });
});

describe("document state", () => {
  it("only résumé and job description are interview kinds", () => {
    expect(isInterviewKind("resume")).toBe(true);
    expect(isInterviewKind("job_description")).toBe(true);
    expect(isInterviewKind("study_material")).toBe(false);
    expect(isInterviewKind(undefined)).toBe(false);
  });
  it("picks the newest non-superseded version and detects processing", () => {
    const d = doc("a", "resume", "2026-10-01", [
      version(1, "superseded"),
      version(2, "active"),
      version(3, "extracting"),
    ]);
    expect(currentVersion(d)?.version).toBe(3);
    expect(isProcessing(currentVersion(d))).toBe(true);
    expect(isProcessing(version(2, "active"))).toBe(false);
    expect(isProcessing(undefined)).toBe(false);
  });
  it("chooses the newest document of a kind, as the plan does", () => {
    const docs = [
      doc("old", "resume", "2026-09-01", []),
      doc("new", "resume", "2026-10-02", []),
      doc("jd", "job_description", "2026-09-30", []),
    ];
    expect(documentOfKind(docs, "resume")?.id).toBe("new");
    expect(documentOfKind(docs, "job_description")?.id).toBe("jd");
    expect(documentOfKind([], "resume")).toBeUndefined();
  });
  it("labels every status in plain language", () => {
    expect(statusLabel(undefined)).toBe("Not uploaded");
    expect(statusLabel(version(1, "active"))).toBe("Ready");
    expect(statusLabel(version(1, "failed"))).toBe("Could not be processed");
  });
  it("explains flags, and says injection-like text is data", () => {
    expect(flagNotes({})).toEqual([]);
    const notes = flagNotes({ needs_ocr: true, suspected_injection: true });
    expect(notes.some((n) => /scanned/.test(n))).toBe(true);
    expect(notes.some((n) => /never followed/.test(n))).toBe(true);
  });
});

describe("asRunnable", () => {
  it("keeps the three runnable languages and falls back to Python", () => {
    expect(asRunnable("typescript")).toBe("typescript");
    expect(asRunnable("javascript")).toBe("javascript");
    expect(asRunnable("python")).toBe("python");
    expect(asRunnable("go")).toBe("python");
    expect(asRunnable(undefined)).toBe("python");
  });
});
