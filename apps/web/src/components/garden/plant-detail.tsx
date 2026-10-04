"use client";

import type {
  Character,
  Dimension,
  EvidenceItem,
  FocusTarget,
  GardenDataset,
  PlantState,
} from "@sg/contracts";

import { EvidenceCard } from "./evidence-card";
import { DimensionBars, PART_LABEL, Panel, StageChip, cap, formatDay } from "./primitives";

/** Left rail at plant and part level: per-dimension scores, review date, and the evidence. */
export function PlantDetail({
  dataset,
  plant,
  part,
  evidence,
  onFocus,
  onPractise,
}: {
  dataset: GardenDataset;
  plant: PlantState;
  part: Dimension | null;
  /** Evidence visible under the current filters and time. */
  evidence: EvidenceItem[];
  onFocus: (t: FocusTarget) => void;
  onPractise: (c: Character, plantKey: string) => void;
}) {
  const key = plant.meta.key;
  const mine = evidence.filter((e) => e.plantKey === key);
  const partEvidence = part ? mine.filter((e) => e.dimension === part) : [];
  const memories = dataset.memories.filter((m) => m.affects.includes(key));
  const grove = dataset.groves.find((g) => g.id === plant.meta.grove);

  return (
    <div className="flex flex-col gap-4">
      <Panel id="plant-head">
        <p className="text-[0.65rem] uppercase tracking-[0.2em] text-foreground/50">
          {grove?.title}
        </p>
        <h2 id="plant-head-title" className="mt-1 text-lg font-semibold leading-tight">
          {plant.meta.title}
        </h2>
        <div className="mt-2">
          <StageChip stage={plant.stage} wilting={plant.wilting} />
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
          <div>
            <dt className="text-foreground/50">Next review</dt>
            <dd>
              {plant.nextReviewAt
                ? (plant.wilting ? "Overdue since " : "") + formatDay(plant.nextReviewAt)
                : "None yet"}
            </dd>
          </div>
          <div>
            <dt className="text-foreground/50">Evidence</dt>
            <dd>
              {plant.evidenceCount.independent} independent, {plant.evidenceCount.assisted} assisted
            </dd>
          </div>
        </dl>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" onClick={() => onPractise("drona", key)} className={ctaClass}>
            Practise with Drona
          </button>
          <button type="button" onClick={() => onPractise("arjuna", key)} className={ctaClass}>
            Practise with Arjuna
          </button>
        </div>
      </Panel>

      <Panel id="plant-dims" title="Scores by plant part">
        <DimensionBars independent={plant.independent} assisted={plant.assisted} />
        <div className="mt-3 flex flex-wrap gap-1.5" role="group" aria-label="Zoom to a plant part">
          {(Object.keys(PART_LABEL) as Dimension[]).map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={part === d}
              onClick={() => onFocus({ level: "part", plantKey: key, part: d })}
              className="rounded-full border border-white/10 px-2.5 py-1 text-[0.7rem] outline-none transition hover:border-glow/60 focus-visible:ring-2 focus-visible:ring-glow/60 aria-pressed:border-glow aria-pressed:bg-glow/10 aria-pressed:text-glow"
            >
              {PART_LABEL[d].split(" · ")[0]}
            </button>
          ))}
        </div>
      </Panel>

      {part && (
        <Panel id="plant-part-evidence" title={`Evidence: ${PART_LABEL[part]}`}>
          {partEvidence.length === 0 ? (
            <p className="text-xs text-foreground/60">
              No visible evidence for this part. Nothing grows without it.
            </p>
          ) : (
            <ul className="space-y-3">
              {partEvidence.map((e) => (
                <li key={e.id}>
                  <EvidenceCard evidence={e} />
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}

      <Panel id="plant-memory" title="What is remembered about this">
        {memories.length === 0 ? (
          <p className="text-xs text-foreground/60">Nothing yet.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {memories.map((m) => (
              <li key={m.id} className="rounded-lg bg-night/40 p-2.5">
                <p>{m.text}</p>
                <p className="mt-1 text-[0.7rem] text-foreground/50">
                  {cap(m.character)} · {m.layer} · {m.status}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

const ctaClass =
  "rounded-lg bg-moss px-3 py-1.5 text-xs font-medium text-night outline-none transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-glow";
