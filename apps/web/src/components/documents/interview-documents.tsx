"use client";

import type {
  ArjunaPlan,
  DocumentUploadAck,
  InterviewDocumentKind,
  LearnerDocument,
} from "@sg/contracts";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { PlanCard } from "@/components/arjuna/plan-card";
import {
  listInterviewDocuments,
  previewPlan,
  removeInterviewDocument,
  retryInterviewDocument,
} from "@/app/(app)/interview/prepare/actions";
import {
  ACCEPT_ATTRIBUTE,
  KIND_LABELS,
  currentVersion,
  documentOfKind,
  flagNotes,
  isProcessing,
  statusLabel,
  validateUpload,
} from "@/lib/documents/upload";

const POLL_MS = 2500;
const KINDS: InterviewDocumentKind[] = ["resume", "job_description"];

const HINTS: Record<InterviewDocumentKind, string> = {
  resume:
    "Arjuna asks about the projects and skills you list. They are your own claims: they shape the questions and earn nothing until you show them in the interview.",
  job_description:
    "The role's requirements come first in the plan, so the interview is practice for that job.",
};

export function InterviewDocuments({
  initialDocuments,
  initialPlan,
}: {
  initialDocuments: LearnerDocument[];
  initialPlan: ArjunaPlan | null;
}) {
  const [docs, setDocs] = useState(initialDocuments);
  const [plan, setPlan] = useState(initialPlan);
  const [error, setError] = useState<string | null>(null);
  const settled = useRef(
    new Set(
      initialDocuments.flatMap((d) => {
        const v = currentVersion(d);
        return v && !isProcessing(v) ? [v.id] : [];
      }),
    ),
  );

  const refresh = useCallback(async () => {
    const result = await listInterviewDocuments();
    if (!result.ok) return setError(result.message);
    setDocs(result.data);
    // A version that finished processing changes the plan: rebuild the preview once.
    const fresh = result.data.flatMap((d) => {
      const v = currentVersion(d);
      return v && !isProcessing(v) && !settled.current.has(v.id) ? [v.id] : [];
    });
    if (fresh.length > 0) {
      fresh.forEach((id) => settled.current.add(id));
      const next = await previewPlan();
      if (next.ok) setPlan(next.data);
    }
  }, []);

  const polling = docs.some((d) => isProcessing(currentVersion(d)));
  useEffect(() => {
    if (!polling) return;
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [polling, refresh]);

  const onDeleted = async () => {
    await refresh();
    const next = await previewPlan();
    if (next.ok) setPlan(next.data);
  };

  return (
    <div className="flex flex-col gap-6">
      {error && (
        <p role="alert" className="rounded-xl bg-red-500/10 p-3 text-sm text-red-200">
          {error}
        </p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {KINDS.map((kind) => (
          <Slot
            key={kind}
            kind={kind}
            doc={documentOfKind(docs, kind)}
            onChange={refresh}
            onDeleted={onDeleted}
            onError={setError}
          />
        ))}
      </div>
      {plan && <PlanCard plan={plan} />}
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href="/interview/technical"
          className="rounded-full bg-glow px-5 py-2.5 text-sm font-semibold text-night outline-none focus-visible:ring-2 focus-visible:ring-white"
        >
          Start the technical interview
        </Link>
        <p className="text-xs text-foreground/60">
          Both documents are optional. Delete them any time and the plan falls back to fundamentals.
        </p>
      </div>
    </div>
  );
}

function Slot({
  kind,
  doc,
  onChange,
  onDeleted,
  onError,
}: {
  kind: InterviewDocumentKind;
  doc: LearnerDocument | undefined;
  onChange: () => Promise<void>;
  onDeleted: () => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [local, setLocal] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const version = doc ? currentVersion(doc) : undefined;
  const label = KIND_LABELS[kind];
  const inputId = `upload-${kind}`;

  async function upload(file: File) {
    setLocal(null);
    onError(null);
    const problem = validateUpload(file);
    if (problem) return setLocal(problem);
    setBusy(true);
    try {
      const body = new FormData();
      body.set("file", file, file.name);
      body.set("kind", kind);
      if (doc) body.set("document_id", doc.id);
      const response = await fetch("/api/documents", { method: "POST", body });
      const payload = (await response.json().catch(() => ({}))) as
        Partial<DocumentUploadAck> | { detail?: unknown };
      if (!response.ok) {
        const detail =
          "detail" in payload && typeof payload.detail === "string" ? payload.detail : null;
        setLocal(detail ?? "The upload failed. Try again.");
      } else {
        await onChange();
      }
    } catch {
      setLocal("The upload service is unreachable. Try again.");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  async function remove() {
    if (!doc) return;
    setBusy(true);
    const result = await removeInterviewDocument(doc.id);
    if (!result.ok) setLocal(result.message);
    else await onDeleted();
    setBusy(false);
  }

  async function retry() {
    if (!doc || !version) return;
    setBusy(true);
    const result = await retryInterviewDocument(doc.id, version.id);
    if (!result.ok) setLocal(result.message);
    else await onChange();
    setBusy(false);
  }

  const notes = version ? flagNotes(version.extraction_flags) : [];

  return (
    <section className="glass flex flex-col gap-3 rounded-2xl p-4 sm:p-5">
      <header>
        <h2 className="text-lg font-semibold">{label}</h2>
        <p className="mt-1 text-xs text-foreground/65">{HINTS[kind]}</p>
      </header>
      <p aria-live="polite" className="text-sm">
        <span className="text-foreground/60">Status: </span>
        <span
          className={
            version?.status === "failed"
              ? "text-red-300"
              : version?.status === "active"
                ? "text-glow"
                : ""
          }
        >
          {statusLabel(version)}
        </span>
        {version?.original_filename && (
          <span className="text-foreground/60"> · {version.original_filename}</span>
        )}
      </p>
      {version?.status === "failed" && version.error && (
        <p className="text-xs text-red-300">{version.error}</p>
      )}
      {notes.map((n) => (
        <p key={n} className="text-xs text-amber-200/90">
          {n}
        </p>
      ))}
      {local && (
        <p role="alert" className="text-xs text-red-300">
          {local}
        </p>
      )}
      <div className="mt-auto flex flex-wrap gap-2">
        <label
          htmlFor={inputId}
          className={`cursor-pointer rounded-full bg-white/10 px-4 py-2 text-sm ring-1 ring-white/20 focus-within:ring-2 focus-within:ring-glow ${
            busy ? "pointer-events-none opacity-50" : "hover:bg-white/15"
          }`}
        >
          {busy ? "Working…" : doc ? "Replace file" : "Choose file"}
          <input
            ref={input}
            id={inputId}
            type="file"
            accept={ACCEPT_ATTRIBUTE}
            disabled={busy}
            className="sr-only"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void upload(file);
            }}
          />
        </label>
        {version?.status === "failed" && (
          <button
            type="button"
            onClick={() => void retry()}
            disabled={busy}
            className="rounded-full px-4 py-2 text-sm ring-1 ring-white/20 hover:bg-white/10 disabled:opacity-50"
          >
            Retry
          </button>
        )}
        {doc && (
          <button
            type="button"
            onClick={() => void remove()}
            disabled={busy}
            className="rounded-full px-4 py-2 text-sm text-red-200 ring-1 ring-red-300/30 hover:bg-red-500/10 disabled:opacity-50"
          >
            Delete
          </button>
        )}
      </div>
      <p className="text-[0.7rem] text-foreground/50">PDF, DOCX, TXT or Markdown, up to 10 MB.</p>
    </section>
  );
}
