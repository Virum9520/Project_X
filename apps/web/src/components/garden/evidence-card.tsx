"use client";

import type { EvidenceItem } from "@sg/contracts";
import { useState } from "react";

import { EvidenceBadge, cap, formatDateTime } from "./primitives";

/**
 * One piece of evidence with its provenance. This is what makes every garden change auditable:
 * the exact quote, the judge's reasoning and uncertainty, and the rubric version.
 * Quotes are learner/agent text, so they render as plain text only.
 */
export function EvidenceCard({
  evidence,
  plantTitle,
  compact = false,
  id,
}: {
  evidence: EvidenceItem;
  plantTitle?: string;
  compact?: boolean;
  id?: string;
}) {
  const [disputed, setDisputed] = useState(false);
  const assisted = evidence.kind === "assisted";
  return (
    <article
      id={id}
      className={`rounded-xl border p-3 text-sm ${
        assisted ? "border-dashed border-ember/50 bg-ember/[0.04]" : "border-white/10 bg-night/40"
      }`}
    >
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <EvidenceBadge kind={evidence.kind} />
        <span className="text-xs text-foreground/70">
          {cap(evidence.dimension)}
          {plantTitle ? ` · ${plantTitle}` : ""}
        </span>
        {evidence.status === "provisional" && (
          <span className="rounded-full bg-glow/15 px-2 py-0.5 text-[0.65rem] text-glow">
            provisional, awaiting full judge pass
          </span>
        )}
        <time dateTime={evidence.occurredAt} className="ml-auto text-[0.7rem] text-foreground/50">
          {formatDateTime(evidence.occurredAt)}
        </time>
      </header>

      <blockquote className="mt-2 border-l-2 border-white/15 pl-3 text-foreground/90">
        <p>&ldquo;{evidence.quote}&rdquo;</p>
        <footer className="mt-1 text-[0.7rem] text-foreground/50">
          {cap(evidence.character)}, from{" "}
          {evidence.source === "tests" ? "test results" : evidence.source}
        </footer>
      </blockquote>

      {assisted && evidence.assistNote && (
        <p className="mt-2 text-xs text-ember">Help received: {evidence.assistNote}</p>
      )}

      {!compact && (
        <>
          <p className="mt-2 text-xs text-foreground/70">
            <span className="text-foreground/50">Judge: </span>
            {evidence.rationale}
          </p>
          <footer className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.7rem] text-foreground/50">
            <span>Confidence {Math.round(evidence.confidence * 100)}%</span>
            <span>Rubric {evidence.rubricVersion}</span>
            <button
              type="button"
              aria-pressed={disputed}
              onClick={() => setDisputed((d) => !d)}
              className="ml-auto rounded-md px-2 py-1 text-glow outline-none hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-glow/60"
            >
              {disputed ? "Disputed (sample data, not saved)" : "Dispute this"}
            </button>
          </footer>
        </>
      )}
    </article>
  );
}
