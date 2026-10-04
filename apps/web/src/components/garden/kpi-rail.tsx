"use client";

import { PLANT_STAGES, type FocusTarget, type GardenDataset, type PlantState } from "@sg/contracts";

import {
  independentRatio,
  plantReadiness,
  readiness,
  reviewStats,
  stageCounts,
} from "@/lib/garden/derive";

import { Panel, STAGE_META, StageChip } from "./primitives";

/** Left rail, garden and grove levels. (Plant and part levels swap in `PlantDetail`.) */
export function KpiRail({
  dataset,
  scopePlants,
  focus,
  cutoff,
  streakDays,
  hoursThisWeek,
  onFocus,
}: {
  dataset: GardenDataset;
  /** Matched plants in scope (the whole garden, or the focused grove). */
  scopePlants: PlantState[];
  focus: FocusTarget;
  cutoff: number;
  streakDays: number;
  hoursThisWeek: number;
  onFocus: (t: FocusTarget) => void;
}) {
  const groveId = focus.level === "grove" ? focus.groveId : null;
  const rd = readiness(dataset, scopePlants, groveId ? [groveId] : undefined);
  const counts = stageCounts(scopePlants);
  const review = reviewStats(scopePlants, cutoff);
  const ratio = independentRatio(scopePlants);
  const total = scopePlants.length;
  const weights = dataset.readiness.dimensionWeights;
  const weakest = scopePlants
    .filter((p) => p.stage !== "unassessed")
    .toSorted((a, b) => plantReadiness(a, weights) - plantReadiness(b, weights))
    .slice(0, 4);
  const untouched = scopePlants.filter((p) => p.stage === "unassessed").length;
  const groveTitle = groveId ? dataset.groves.find((g) => g.id === groveId)?.title : null;

  return (
    <div className="flex flex-col gap-4">
      <Panel id="kpi-readiness" title={groveTitle ? `${groveTitle} readiness` : "Readiness"}>
        <div className="flex items-center gap-4">
          <Ring value={rd.overall} label={`${groveTitle ?? "Overall"} readiness`} />
          <p className="text-xs leading-relaxed text-foreground/60">
            For <span className="text-foreground/90">{dataset.readiness.targetRole}</span>. Counts
            independent evidence only; hints earn nothing here.
          </p>
        </div>
        {!groveId && (
          <ul className="mt-4 space-y-1.5" aria-label="Readiness by domain">
            {rd.byGrove
              .filter((g) => g.plants > 0)
              .map((g) => (
                <li key={g.grove}>
                  <button
                    type="button"
                    onClick={() => onFocus({ level: "grove", groveId: g.grove })}
                    className="group flex w-full items-center gap-2 rounded-md px-1 py-1 text-left text-xs outline-none hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-glow/60"
                  >
                    <span className="w-24 shrink-0 truncate text-foreground/70 group-hover:text-foreground">
                      {dataset.groves.find((x) => x.id === g.grove)?.title.split(" & ")[0]}
                    </span>
                    <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
                      <span
                        className="block h-full rounded-full bg-moss"
                        style={{ width: `${Math.round(g.score)}%` }}
                      />
                    </span>
                    <span className="w-8 text-right font-mono tabular-nums text-foreground/70">
                      {Math.round(g.score)}
                    </span>
                  </button>
                </li>
              ))}
          </ul>
        )}
      </Panel>

      <Panel id="kpi-stages" title="Concepts by stage">
        <div
          className="flex h-2.5 overflow-hidden rounded-full bg-white/5"
          role="img"
          aria-label={PLANT_STAGES.map((s) => `${counts[s]} ${STAGE_META[s].label}`).join(", ")}
        >
          {PLANT_STAGES.map((s) =>
            counts[s] ? (
              <span
                key={s}
                className={s === "assisted" ? "hatch" : ""}
                style={{
                  width: `${(counts[s] / Math.max(total, 1)) * 100}%`,
                  background: s === "assisted" ? undefined : STAGE_META[s].color,
                }}
              />
            ) : null,
          )}
        </div>
        <ul className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
          {PLANT_STAGES.map((s) => (
            <li key={s} className="flex items-center justify-between gap-2">
              <span className="inline-flex items-center gap-1.5 text-foreground/70">
                <span aria-hidden style={{ color: STAGE_META[s].color }}>
                  {STAGE_META[s].glyph}
                </span>
                {STAGE_META[s].label}
              </span>
              <span className="font-mono tabular-nums">{counts[s]}</span>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel id="kpi-ratio" title="Independent vs assisted">
        <div className="flex items-end justify-between">
          <p className="text-3xl font-semibold tabular-nums">
            {ratio.share === null ? "–" : `${Math.round(ratio.share * 100)}%`}
          </p>
          <p className="pb-1 text-xs text-foreground/60">of evidence is independent</p>
        </div>
        <div
          className="mt-3 flex h-2.5 overflow-hidden rounded-full bg-white/5"
          role="img"
          aria-label={`${ratio.independent} independent, ${ratio.assisted} assisted`}
        >
          <span className="bg-moss" style={{ width: `${(ratio.share ?? 0) * 100}%` }} />
          <span className="hatch flex-1" />
        </div>
        <p className="mt-2 flex justify-between text-xs text-foreground/60">
          <span>{ratio.independent} independent</span>
          <span className="text-ember">{ratio.assisted} assisted</span>
        </p>
      </Panel>

      <Panel id="kpi-reviews" title="Reviews">
        <div className="grid grid-cols-2 gap-3 text-center">
          <Stat
            value={review.overdue}
            label="Wilting (overdue)"
            tone={review.overdue ? "warn" : "ok"}
          />
          <Stat value={review.dueSoon} label="Due in 3 days" />
        </div>
      </Panel>

      {groveId ? (
        <Panel id="kpi-weakest" title="Weakest concepts">
          {weakest.length === 0 ? (
            <p className="text-xs text-foreground/60">No evidence in this grove yet.</p>
          ) : (
            <ol className="space-y-1">
              {weakest.map((p) => (
                <li key={p.meta.key}>
                  <button
                    type="button"
                    onClick={() => onFocus({ level: "plant", plantKey: p.meta.key })}
                    className="flex w-full items-center justify-between gap-2 rounded-md px-1.5 py-1.5 text-left text-sm outline-none hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-glow/60"
                  >
                    <span className="truncate">{p.meta.title}</span>
                    <StageChip stage={p.stage} wilting={p.wilting} />
                  </button>
                </li>
              ))}
            </ol>
          )}
          <p className="mt-2 text-xs text-foreground/50">{untouched} not yet assessed.</p>
        </Panel>
      ) : (
        <Panel id="kpi-habit" title="This week">
          <div className="grid grid-cols-2 gap-3 text-center">
            <Stat value={streakDays} label="Day streak" />
            <Stat value={Number(hoursThisWeek.toFixed(1))} label="Hours practised" />
          </div>
        </Panel>
      )}
    </div>
  );
}

function Stat({ value, label, tone }: { value: number; label: string; tone?: "warn" | "ok" }) {
  return (
    <div className="rounded-xl bg-night/40 px-2 py-3">
      <p className={`text-2xl font-semibold tabular-nums ${tone === "warn" ? "text-ember" : ""}`}>
        {value}
      </p>
      <p className="mt-0.5 text-[0.7rem] text-foreground/60">{label}</p>
    </div>
  );
}

function Ring({ value, label }: { value: number; label: string }) {
  const r = 34;
  const c = 2 * Math.PI * r;
  const pct = Math.round(value);
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      className="relative size-24 shrink-0"
    >
      <svg viewBox="0 0 80 80" className="size-full -rotate-90" aria-hidden>
        <circle
          cx="40"
          cy="40"
          r={r}
          fill="none"
          stroke="rgb(255 255 255 / 0.08)"
          strokeWidth="7"
        />
        <circle
          cx="40"
          cy="40"
          r={r}
          fill="none"
          stroke="var(--moss)"
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={`${(value / 100) * c} ${c}`}
          className="transition-[stroke-dasharray] duration-700"
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-2xl font-semibold tabular-nums">
        {pct}
      </span>
    </div>
  );
}
