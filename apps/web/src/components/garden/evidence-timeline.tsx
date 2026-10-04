"use client";

import type { EvidenceItem, GardenDataset, GrowthEvent } from "@sg/contracts";
import { useState } from "react";

import { EvidenceCard } from "./evidence-card";
import { EvidenceBadge, Panel, cap, formatDateTime } from "./primitives";

/**
 * Chronological garden changes. Every row is a growth event and cannot render without the evidence
 * it cites: expand a row to read the exact quote, the judge's reasoning and the rubric version.
 */
export function EvidenceTimeline({
  dataset,
  growthEvents,
  evidence,
  scopeKeys,
  scopeLabel,
}: {
  dataset: GardenDataset;
  growthEvents: GrowthEvent[];
  evidence: EvidenceItem[];
  scopeKeys: Set<string>;
  scopeLabel: string;
}) {
  const [limit, setLimit] = useState(8);
  const evById = new Map(evidence.map((e) => [e.id, e]));
  const titleOf = new Map(dataset.plants.map((p) => [p.key, p.title]));
  const rows = growthEvents.filter((g) => scopeKeys.has(g.plantKey));

  return (
    <Panel id="evidence-timeline" title={`Evidence timeline · ${scopeLabel}`}>
      {rows.length === 0 ? (
        <p className="text-sm text-foreground/60">
          Nothing has grown here under the current filters. Growth only appears with evidence.
        </p>
      ) : (
        <ol className="relative space-y-2 border-l border-white/10 pl-4">
          {rows.slice(0, limit).map((g) => {
            const cited = g.evidenceIds
              .map((id) => evById.get(id))
              .filter((e): e is EvidenceItem => !!e);
            const kind = cited[0]?.kind ?? "independent";
            return (
              <li key={g.id} className="relative">
                <span
                  aria-hidden
                  className={`absolute -left-[1.4rem] top-3 size-2.5 rounded-full ring-4 ring-night ${kind === "independent" ? "bg-moss" : "hatch bg-ember/40"}`}
                />
                <details className="group rounded-xl border border-white/10 bg-night/30 open:bg-night/50">
                  <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-3 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-glow [&::-webkit-details-marker]:hidden">
                    <span
                      aria-hidden
                      className="text-foreground/40 transition group-open:rotate-90"
                    >
                      ▸
                    </span>
                    <span className="font-medium">{titleOf.get(g.plantKey)}</span>
                    <span className="text-foreground/70">{g.summary}</span>
                    <EvidenceBadge kind={kind} />
                    {g.fromStage !== g.toStage && (
                      <span className="text-xs text-moss">
                        {cap(g.fromStage)} → {cap(g.toStage)}
                      </span>
                    )}
                    <time
                      dateTime={g.occurredAt}
                      className="ml-auto text-[0.7rem] text-foreground/50"
                    >
                      {formatDateTime(g.occurredAt)} · rev {g.revision}
                    </time>
                  </summary>
                  <div className="space-y-2 px-3 pb-3">
                    {cited.map((e) => (
                      <EvidenceCard key={e.id} evidence={e} />
                    ))}
                  </div>
                </details>
              </li>
            );
          })}
        </ol>
      )}
      {rows.length > limit && (
        <button
          type="button"
          onClick={() => setLimit((l) => l + 8)}
          className="mt-3 rounded-lg px-3 py-1.5 text-sm text-glow outline-none hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-glow/60"
        >
          Show more ({rows.length - limit} older)
        </button>
      )}
    </Panel>
  );
}
