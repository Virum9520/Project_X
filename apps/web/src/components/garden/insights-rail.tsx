"use client";

import type {
  Character,
  EvidenceItem,
  FocusTarget,
  GardenDataset,
  GrowthEvent,
} from "@sg/contracts";

import { EvidenceBadge, Panel, cap, formatDay } from "./primitives";

/** Right rail: what changed and why (with citations), misconceptions, and the next best practice. */
export function InsightsRail({
  dataset,
  growthEvents,
  evidence,
  scopeKeys,
  scopeLabel,
  onFocus,
  onPractise,
  cutoff,
}: {
  dataset: GardenDataset;
  /** Growth events visible under filters and time, newest first. */
  growthEvents: GrowthEvent[];
  evidence: EvidenceItem[];
  /** Plant keys in the current zoom scope. */
  scopeKeys: Set<string>;
  scopeLabel: string;
  onFocus: (t: FocusTarget) => void;
  onPractise: (c: Character, plantKey: string) => void;
  cutoff: number;
}) {
  const evById = new Map(evidence.map((e) => [e.id, e]));
  const titleOf = new Map(dataset.plants.map((p) => [p.key, p.title]));
  const feed = growthEvents.filter((g) => scopeKeys.has(g.plantKey)).slice(0, 5);
  const misconceptions = dataset.misconceptions
    .filter((m) => scopeKeys.has(m.plantKey) && Date.parse(m.lastSeenAt) <= cutoff)
    .toSorted((a, b) => b.occurrences - a.occurrences)
    .slice(0, 3);
  const next = dataset.nextBest.find((n) => scopeKeys.has(n.plantKey)) ?? dataset.nextBest[0];

  return (
    <div className="flex flex-col gap-4">
      <Panel id="ins-changed" title="What changed and why">
        <p className="-mt-1 mb-3 text-xs text-foreground/50">Sanjaya · {scopeLabel}</p>
        {feed.length === 0 ? (
          <p className="text-sm text-foreground/60">No garden changes match these filters.</p>
        ) : (
          <ol className="space-y-3">
            {feed.map((g) => {
              const cited = g.evidenceIds
                .map((id) => evById.get(id))
                .filter(Boolean) as EvidenceItem[];
              const first = cited[0];
              return (
                <li key={g.id} className="text-sm">
                  <button
                    type="button"
                    onClick={() => onFocus({ level: "plant", plantKey: g.plantKey })}
                    className="text-left font-medium outline-none hover:text-glow focus-visible:underline"
                  >
                    {titleOf.get(g.plantKey)}: {g.summary.toLowerCase()}
                  </button>
                  <span className="ml-2 text-[0.7rem] text-foreground/50">
                    {formatDay(g.occurredAt)}
                  </span>
                  {first && (
                    <p className="mt-1 flex flex-wrap items-start gap-x-2 gap-y-1 text-xs text-foreground/60">
                      <EvidenceBadge kind={first.kind} />
                      <span className="min-w-0 flex-1">
                        Because: &ldquo;{first.quote.slice(0, 90)}
                        {first.quote.length > 90 ? "…" : ""}&rdquo;
                      </span>
                    </p>
                  )}
                  {g.fromStage !== g.toStage && (
                    <p className="mt-1 text-[0.7rem] text-moss">
                      {cap(g.fromStage)} → {cap(g.toStage)}
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </Panel>

      <Panel id="ins-misc" title="Top misconceptions">
        {misconceptions.length === 0 ? (
          <p className="text-sm text-foreground/60">None recorded in this view.</p>
        ) : (
          <ul className="space-y-2.5">
            {misconceptions.map((m) => (
              <li key={m.id} className="text-sm">
                <p>{m.text}</p>
                <p className="mt-0.5 text-[0.7rem] text-foreground/50">
                  {titleOf.get(m.plantKey)} · seen {m.occurrences}× · last {formatDay(m.lastSeenAt)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {next && (
        <Panel id="ins-next" title="Next best practice" className="ring-1 ring-moss/30">
          <p className="font-medium">{next.title}</p>
          <p className="mt-1 text-xs leading-relaxed text-foreground/60">{next.reason}</p>
          <p className="mt-1 text-[0.7rem] text-foreground/50">
            {titleOf.get(next.plantKey)} · about {next.minutes} min · cites{" "}
            {next.evidenceIds.length} evidence item{next.evidenceIds.length === 1 ? "" : "s"}
          </p>
          <button
            type="button"
            onClick={() => onPractise(next.character, next.plantKey)}
            className="mt-3 w-full rounded-xl bg-moss px-4 py-2 text-sm font-medium text-night outline-none transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-glow"
          >
            Practise with {cap(next.character)}
          </button>
        </Panel>
      )}
    </div>
  );
}
