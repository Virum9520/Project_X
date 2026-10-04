"use client";

import {
  DIMENSION_TO_PART,
  type Dimension,
  type FocusTarget,
  type GardenDataset,
  type PlantState,
} from "@sg/contracts";

import { DIMENSIONS } from "@/lib/garden/derive";

import { Panel, StageChip, formatDay } from "./primitives";

const pct = (v: number | null) => (v === null ? null : Math.round(v * 100));

/** The always-available 2D view of the garden, kept in sync with filters, zoom and time travel. */
export function PlantsTable({
  dataset,
  plants,
  focus,
  onFocus,
}: {
  dataset: GardenDataset;
  plants: PlantState[];
  focus: FocusTarget;
  onFocus: (t: FocusTarget) => void;
}) {
  const groveTitle = new Map(dataset.groves.map((g) => [g.id, g.title]));
  const selected = focus.level === "plant" || focus.level === "part" ? focus.plantKey : null;
  const rows = plants.filter((p) => p.matched);

  return (
    <Panel id="plants-table" title="Table view">
      <details>
        <summary className="cursor-pointer rounded-md py-1 text-sm text-glow outline-none focus-visible:ring-2 focus-visible:ring-glow/60">
          Show every concept as a table ({rows.length})
        </summary>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse text-left text-sm">
            <caption className="sr-only">
              Concept plants with stage, independent and assisted scores per plant part, and next
              review
            </caption>
            <thead className="text-[0.65rem] uppercase tracking-wider text-foreground/50">
              <tr>
                <th scope="col" className="py-2 pr-3 font-medium">
                  Concept
                </th>
                <th scope="col" className="px-2 font-medium">
                  Stage
                </th>
                {DIMENSIONS.map((d: Dimension) => (
                  <th key={d} scope="col" className="px-2 font-medium">
                    {DIMENSION_TO_PART[d]}
                  </th>
                ))}
                <th scope="col" className="pl-2 font-medium">
                  Next review
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr
                  key={p.meta.key}
                  className={`border-t border-white/5 ${selected === p.meta.key ? "bg-glow/10" : ""}`}
                >
                  <th scope="row" className="py-1.5 pr-3 font-normal">
                    <button
                      type="button"
                      onClick={() => onFocus({ level: "plant", plantKey: p.meta.key })}
                      className="text-left outline-none hover:text-glow focus-visible:underline"
                    >
                      {p.meta.title}
                    </button>
                    <span className="block text-[0.65rem] text-foreground/40">
                      {groveTitle.get(p.meta.grove)}
                    </span>
                  </th>
                  <td className="px-2">
                    <StageChip stage={p.stage} wilting={p.wilting} />
                  </td>
                  {DIMENSIONS.map((d) => (
                    <td key={d} className="px-2 font-mono text-xs tabular-nums">
                      {pct(p.independent[d]) ?? <span className="text-foreground/30">–</span>}
                      {p.assisted[d] !== null && (
                        <span className="ml-1 text-ember" title="assisted score">
                          (a {pct(p.assisted[d])})
                        </span>
                      )}
                    </td>
                  ))}
                  <td className="pl-2 text-xs text-foreground/70">
                    {p.nextReviewAt ? formatDay(p.nextReviewAt) : "–"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[0.7rem] text-foreground/50">
            Scores are independent evidence. <span className="text-ember">(a n)</span> is
            assisted-only evidence, counted separately.
          </p>
        </div>
      </details>
    </Panel>
  );
}
