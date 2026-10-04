"use client";

import { PLANT_STAGES, type GardenDataset, type PlantState } from "@sg/contracts";

import { readiness, stageCounts } from "@/lib/garden/derive";

import { STAGE_META } from "./primitives";

/** Big, plain-language numbers and bars under the garden. */
export function StatsOverview({
  dataset,
  plants,
  streakDays,
  hoursThisWeek,
}: {
  dataset: GardenDataset;
  plants: PlantState[];
  streakDays: number;
  hoursThisWeek: number;
}) {
  const rd = readiness(dataset, plants);
  const counts = stageCounts(plants);
  const growing = plants.length - counts.unassessed;
  const maxCount = Math.max(1, ...PLANT_STAGES.map((s) => counts[s]));

  const tiles = [
    {
      label: "Job readiness",
      value: `${Math.round(rd.overall)}%`,
      hint: "from proven skills only",
    },
    {
      label: "Plants growing",
      value: `${growing}/${plants.length}`,
      hint: "topics you've started",
    },
    { label: "Day streak", value: String(streakDays), hint: "days in a row" },
    { label: "Hours this week", value: hoursThisWeek.toFixed(1), hint: "practice time" },
  ];

  return (
    <section aria-label="Your stats" className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-2xl border border-white/10 bg-dusk/60 p-5">
            <p className="text-lg text-foreground/70">{t.label}</p>
            <p className="mt-1 text-5xl font-semibold text-glow">{t.value}</p>
            <p className="mt-1 text-base text-foreground/50">{t.hint}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-dusk/60 p-5">
          <h3 className="text-2xl font-semibold">Readiness by topic</h3>
          <ul className="mt-4 space-y-3">
            {rd.byGrove.map((g) => (
              <li key={g.grove}>
                <div className="flex justify-between text-lg">
                  <span>{dataset.groves.find((x) => x.id === g.grove)?.title}</span>
                  <span className="text-foreground/70">{Math.round(g.score)}%</span>
                </div>
                <div className="mt-1 h-3 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-moss"
                    style={{ width: `${Math.max(2, Math.round(g.score))}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-2xl border border-white/10 bg-dusk/60 p-5">
          <h3 className="text-2xl font-semibold">How your plants are doing</h3>
          <ul className="mt-4 space-y-3">
            {PLANT_STAGES.map((s) => (
              <li key={s}>
                <div className="flex justify-between text-lg">
                  <span>{STAGE_META[s].label}</span>
                  <span className="text-foreground/70">{counts[s]}</span>
                </div>
                <div className="mt-1 h-3 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${(counts[s] / maxCount) * 100}%`,
                      background: STAGE_META[s].color,
                    }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
