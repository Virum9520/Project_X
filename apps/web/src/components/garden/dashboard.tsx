"use client";

import type { Character, FocusTarget, GardenDataset } from "@sg/contracts";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { DAY_MS } from "@/lib/garden/derive";
import { type DashboardState, focusGrove } from "@/lib/garden/state";
import { useLiveGrowth } from "@/lib/session/use-live-growth";

import { AskSanjaya } from "./ask-sanjaya";
import { EvidenceTimeline } from "./evidence-timeline";
import { FiltersBar } from "./filters-bar";
import { GardenSceneSlot } from "./garden-scene-slot";
import { InsightsRail } from "./insights-rail";
import { KpiRail } from "./kpi-rail";
import { MemoryPanel } from "./memory-panel";
import { StartingLevelsNotice } from "./starting-levels-notice";
import { StatsOverview } from "./stats-overview";
import { PlantDetail } from "./plant-detail";
import { PlantsTable } from "./plants-table";
import { PART_LABEL, cap, formatDateTime } from "./primitives";
import { useGardenAudioState } from "../soundscape/audio-state";
import { SoundControls } from "../soundscape/sound-controls";
import { SoundscapeProvider } from "../soundscape/soundscape-provider";
import { Timeline } from "./timeline";
import { useGardenDashboard } from "./use-garden-dashboard";

/** The Garden Dashboard shell: filters, KPI rail, 3D slot, insights rail, timeline, memory. */
export function GardenDashboard({
  dataset,
  initialState,
  isMock,
  fallbackReason,
}: {
  dataset: GardenDataset;
  initialState: DashboardState;
  isMock: boolean;
  /** Why sample data is showing (development fallback only). */
  fallbackReason?: string;
}) {
  const { state, view, series, actions } = useGardenDashboard(dataset, initialState);
  const { focus, filters, scrubDate } = state;
  const [notice, setNotice] = useState<string | null>(null);
  const router = useRouter();
  // Live provisional growth from a voice session (this tab or another) makes plants glow.
  const live = useLiveGrowth();

  // Esc zooms out one level (unless the user is typing in a field).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const el = e.target as HTMLElement | null;
      if (el && ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)) return;
      actions.zoomOut();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [actions]);

  const onPractise = (c: Character, plantKey: string) => {
    if (c === "drona") {
      router.push(`/session?concept=${encodeURIComponent(plantKey)}`);
      return;
    }
    if (c === "arjuna") {
      router.push(`/interview/technical?concept=${encodeURIComponent(plantKey)}`);
      return;
    }
    const title = dataset.plants.find((p) => p.key === plantKey)?.title;
    setNotice(
      `Starting ${cap(c)} on ${title} arrives with that character's session (Drona and Arjuna are available now).`,
    );
  };

  const grove = focusGrove(focus, dataset);
  const focusedPlant =
    focus.level === "plant" || focus.level === "part"
      ? view.plants.find((p) => p.meta.key === focus.plantKey)
      : undefined;

  const scopePlants = useMemo(() => {
    if (focusedPlant) return [focusedPlant];
    return view.matched.filter((p) => !grove || p.meta.grove === grove);
  }, [focusedPlant, view.matched, grove]);
  const scopeKeys = useMemo(() => new Set(scopePlants.map((p) => p.meta.key)), [scopePlants]);

  const scopeLabel = focusedPlant
    ? focusedPlant.meta.title
    : grove
      ? (dataset.groves.find((g) => g.id === grove)?.title ?? "Grove")
      : "Whole garden";

  const livePulse = live.pulseConceptIds;
  const recentGrowth = useMemo(
    () => [
      ...new Set([
        ...view.growthEvents
          .filter((g) => view.cutoff - Date.parse(g.occurredAt) < DAY_MS * 1.5)
          .map((g) => g.plantKey),
        ...(view.isPast ? [] : livePulse),
      ]),
    ],
    [view.growthEvents, view.cutoff, view.isPast, livePulse],
  );

  const revision = useMemo(
    () => view.growthEvents.reduce((max, g) => Math.max(max, g.revision), 0),
    [view.growthEvents],
  );

  const audioState = useGardenAudioState(view.plants);

  return (
    <SoundscapeProvider garden={audioState}>
      <main className="mx-auto flex w-full max-w-[1800px] flex-1 flex-col gap-4 px-4 pb-16 pt-24 sm:px-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-base uppercase tracking-[0.3em] text-glow">Garden dashboard</p>
            <h1 className="mt-1 text-4xl font-semibold sm:text-5xl">Your garden</h1>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-foreground/60">
            <SoundControls recentGrowthPlantKeys={recentGrowth} />
            {isMock && (
              <span
                className="rounded-full bg-ember/15 px-2.5 py-1 text-ember ring-1 ring-ember/40"
                title={fallbackReason ? `API unavailable (${fallbackReason})` : undefined}
              >
                Sample data
              </span>
            )}
            <span>
              Updated {formatDateTime(dataset.freshness.projectionAt)} · rules{" "}
              {dataset.freshness.rulesVersion} · {dataset.freshness.curriculum}
            </span>
          </div>
        </header>

        <PracticeLinks />

        {state.scrubDate && (
          <div
            role="status"
            className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-glow/30 bg-glow/10 px-4 py-2 text-sm text-glow"
          >
            <span>
              Time travel: showing the garden as it was on {scrubDate}. This is a read-only replay
              of past revisions.
            </span>
            <button
              type="button"
              onClick={() => actions.scrubTo(null)}
              className="rounded-lg bg-glow/20 px-3 py-1 outline-none hover:bg-glow/30 focus-visible:ring-2 focus-visible:ring-glow"
            >
              Back to now
            </button>
          </div>
        )}

        <div className="flex min-w-0 flex-col gap-3">
          <Breadcrumb
            focus={focus}
            dataset={dataset}
            onFocus={actions.focusOn}
            onZoomOut={actions.zoomOut}
          />
          <GardenSceneSlot
            groves={dataset.groves}
            plants={view.plants}
            focus={focus}
            onFocusChange={actions.focusOn}
            asOf={new Date(view.cutoff).toISOString()}
            isTimeTravel={view.isPast}
            recentGrowthPlantKeys={recentGrowth}
            evidence={view.evidence}
            prerequisites={dataset.prerequisites}
            revision={revision}
            ruleVersion={dataset.freshness.rulesVersion}
          />
          <p className="sr-only" role="status" aria-live="polite">
            Focused on {scopeLabel}.
          </p>
          {notice && (
            <p
              role="status"
              className="flex items-start justify-between gap-3 rounded-xl bg-white/5 px-3 py-2 text-sm text-foreground/80"
            >
              <span>{notice}</span>
              <button
                type="button"
                onClick={() => setNotice(null)}
                aria-label="Dismiss"
                className="rounded px-1 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-glow"
              >
                ×
              </button>
            </p>
          )}
        </div>

        {focusedPlant && (
          <PlantDetail
            dataset={dataset}
            plant={focusedPlant}
            part={focus.level === "part" ? focus.part : null}
            evidence={view.evidence}
            onFocus={actions.focusOn}
            onPractise={onPractise}
          />
        )}

        <StartingLevelsNotice dataset={dataset} />

        <StatsOverview
          dataset={dataset}
          plants={view.plants}
          streakDays={dataset.streakDays}
          hoursThisWeek={view.hoursThisWeek}
        />

        <details className="rounded-2xl border border-white/10 bg-dusk/40 p-4 sm:p-5">
          <summary className="cursor-pointer select-none text-2xl font-semibold outline-none focus-visible:ring-2 focus-visible:ring-glow">
            Detailed analytics
            <span className="ml-3 text-lg font-normal text-foreground/50">
              filters, timeline, evidence, memory
            </span>
          </summary>
          <div className="mt-5 flex flex-col gap-4">
            <FiltersBar
              dataset={dataset}
              filters={filters}
              onChange={actions.setFilters}
              onClear={actions.clearFilters}
              matchedCount={view.matched.length}
            />

            <div className="grid gap-4 lg:grid-cols-2">
              <aside aria-label="Key metrics">
                <KpiRail
                  dataset={dataset}
                  scopePlants={scopePlants}
                  focus={focus}
                  cutoff={view.cutoff}
                  streakDays={dataset.streakDays}
                  hoursThisWeek={view.hoursThisWeek}
                  onFocus={actions.focusOn}
                />
              </aside>

              <aside aria-label="Insights" className="flex flex-col gap-4">
                <AskSanjaya dataset={dataset} live={!isMock} onFocus={actions.focusOn} />
                <InsightsRail
                  dataset={dataset}
                  growthEvents={view.growthEvents}
                  evidence={view.evidence}
                  scopeKeys={scopeKeys}
                  scopeLabel={scopeLabel}
                  onFocus={actions.focusOn}
                  onPractise={onPractise}
                  cutoff={view.cutoff}
                />
              </aside>
            </div>

            <Timeline
              series={series}
              sessions={dataset.sessions}
              scrubDate={scrubDate}
              onScrub={actions.scrubTo}
              rangeFrom={filters.dateFrom}
              rangeTo={filters.dateTo}
            />

            <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
              <EvidenceTimeline
                dataset={dataset}
                growthEvents={view.growthEvents}
                evidence={view.evidence}
                scopeKeys={scopeKeys}
                scopeLabel={scopeLabel}
              />
              <MemoryPanel
                dataset={dataset}
                cutoff={view.cutoff}
                live={!isMock}
                onFocusPlant={(key) => actions.focusOn({ level: "plant", plantKey: key })}
              />
            </div>

            <PlantsTable
              dataset={dataset}
              plants={view.plants}
              focus={focus}
              onFocus={actions.focusOn}
            />
          </div>
        </details>
      </main>
    </SoundscapeProvider>
  );
}

const PRACTICE: { href: Route; label: string; hint: string }[] = [
  { href: "/session", label: "Voice session", hint: "Drona, concept by concept" },
  { href: "/interview", label: "HR and panel interview", hint: "Vidura and Arjuna" },
  { href: "/interview/technical", label: "Technical interview", hint: "Arjuna, with code" },
];

/** Entry points to every practice mode, so the garden is one click from the next session. */
function PracticeLinks() {
  return (
    <nav aria-label="Practice" className="flex flex-wrap items-center gap-3 text-lg">
      <span className="text-base uppercase tracking-[0.2em] text-foreground/60">Practise</span>
      {PRACTICE.map((p) => (
        <Link
          key={p.href}
          href={p.href}
          title={p.hint}
          className="rounded-xl border border-white/15 px-5 py-2.5 text-foreground/90 outline-none hover:border-glow/40 hover:text-foreground focus-visible:ring-2 focus-visible:ring-glow"
        >
          {p.label}
        </Link>
      ))}
    </nav>
  );
}

function Breadcrumb({
  focus,
  dataset,
  onFocus,
  onZoomOut,
}: {
  focus: FocusTarget;
  dataset: GardenDataset;
  onFocus: (t: FocusTarget) => void;
  onZoomOut: () => void;
}) {
  const grove = focusGrove(focus, dataset);
  const plantKey = focus.level === "plant" || focus.level === "part" ? focus.plantKey : null;
  const crumbs: { label: string; target: FocusTarget; current: boolean }[] = [
    { label: "Garden", target: { level: "garden" }, current: focus.level === "garden" },
  ];
  if (grove)
    crumbs.push({
      label: dataset.groves.find((g) => g.id === grove)?.title ?? grove,
      target: { level: "grove", groveId: grove },
      current: focus.level === "grove",
    });
  if (plantKey)
    crumbs.push({
      label: dataset.plants.find((p) => p.key === plantKey)?.title ?? plantKey,
      target: { level: "plant", plantKey },
      current: focus.level === "plant",
    });
  if (focus.level === "part")
    crumbs.push({ label: PART_LABEL[focus.part].split(" · ")[0]!, target: focus, current: true });

  return (
    <div className="flex items-center justify-between gap-3">
      <nav aria-label="Zoom level">
        <ol className="flex flex-wrap items-center gap-1 text-sm">
          {crumbs.map((c, i) => (
            <li key={c.label} className="flex items-center gap-1">
              {i > 0 && (
                <span aria-hidden className="text-foreground/30">
                  ›
                </span>
              )}
              <button
                type="button"
                aria-current={c.current ? "page" : undefined}
                onClick={() => onFocus(c.target)}
                className={`rounded-md px-1.5 py-0.5 outline-none focus-visible:ring-2 focus-visible:ring-glow ${
                  c.current
                    ? "font-medium text-foreground"
                    : "text-foreground/60 hover:text-foreground"
                }`}
              >
                {c.label}
              </button>
            </li>
          ))}
        </ol>
      </nav>
      {focus.level !== "garden" && (
        <button
          type="button"
          onClick={onZoomOut}
          className="rounded-lg border border-white/10 px-2.5 py-1 text-xs text-foreground/70 outline-none hover:border-white/25 focus-visible:ring-2 focus-visible:ring-glow"
        >
          Zoom out <kbd className="ml-1 rounded bg-white/10 px-1 font-mono text-[0.65rem]">Esc</kbd>
        </button>
      )}
    </div>
  );
}
