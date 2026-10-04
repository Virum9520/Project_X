"use client";

import type { Dimension, GardenSnapshot } from "@sg/contracts";
import {
  focusFromString,
  focusLabel,
  focusToString,
  focusTrail,
  generateGardenLayout,
  MOCK_REVISIONS,
  mockEvidence,
  mockGardenSnapshot,
  withProvisionalGrowth,
  type EvidenceCardData,
  type GardenFocus,
} from "@sg/three";
import type { GardenQuality } from "@sg/three/scene";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const GardenScene = dynamic(() => import("@sg/three/scene").then((m) => m.GardenScene), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-sm text-foreground/60">
      Growing the garden…
    </div>
  ),
});

const LIVE_DIMENSIONS: Dimension[] = ["explanation", "application", "transfer", "retention"];

export function GardenLab({ initialFocus }: { initialFocus: string | null }) {
  const [revision, setRevision] = useState(MOCK_REVISIONS);
  const [playing, setPlaying] = useState(false);
  const [focus, setFocusState] = useState<GardenFocus>(() => focusFromString(initialFocus));
  const [hour, setHour] = useState<number | null>(null);
  const [quality, setQuality] = useState<GardenQuality>("high");
  const [onlyDue, setOnlyDue] = useState(false);
  const [live, setLive] = useState<{ conceptId: string; dimension: Dimension } | null>(null);
  const [selected, setSelected] = useState<EvidenceCardData | null>(null);
  const liveStep = useRef(0);

  const base = useMemo(() => mockGardenSnapshot(revision), [revision]);
  const snapshot: GardenSnapshot = useMemo(
    () => (live ? withProvisionalGrowth(base, live.conceptId, live.dimension, 1) : base),
    [base, live],
  );
  const layout = useMemo(() => generateGardenLayout(snapshot), [snapshot]);

  const setFocus = useCallback((next: GardenFocus) => {
    setFocusState(next);
    setSelected(null);
    const url = new URL(window.location.href);
    if (next.level === "garden") url.searchParams.delete("focus");
    else url.searchParams.set("focus", focusToString(next));
    window.history.replaceState(null, "", url);
  }, []);

  // Time travel: replay revisions so growth animates between them.
  useEffect(() => {
    if (!playing) return;
    const timer = setTimeout(() => {
      setRevision(revision + 1);
      if (revision + 1 >= MOCK_REVISIONS) setPlaying(false);
    }, 1400);
    return () => clearTimeout(timer);
  }, [playing, revision]);

  const matched = useMemo(
    () =>
      onlyDue
        ? new Set(
            snapshot.plants
              .filter((p) => p.status === "due" || p.status === "wilting")
              .map((p) => p.conceptId),
          )
        : null,
    [onlyDue, snapshot],
  );
  const pulse = useMemo(() => new Set(live ? [live.conceptId] : []), [live]);
  const evidence = useCallback(
    (conceptId: string, part: Parameters<typeof mockEvidence>[2]) =>
      mockEvidence(snapshot, conceptId, part),
    [snapshot],
  );

  const simulateLiveGrowth = () => {
    // Pick the focused plant, or the next growing plant, and grow its next dimension provisionally.
    const target =
      focus.level === "plant" || focus.level === "part"
        ? focus.conceptId
        : (snapshot.plants.filter((p) => p.status !== "retained")[liveStep.current % 7]
            ?.conceptId ?? null);
    if (!target) return;
    const plant = snapshot.plants.find((p) => p.conceptId === target);
    const dimension =
      LIVE_DIMENSIONS.find((d) => (plant?.dimensions[d].independent ?? 0) < 0.6) ?? "retention";
    liveStep.current += 1;
    setLive({ conceptId: target, dimension });
  };

  const trail = focusTrail(focus, layout);

  return (
    <div className="relative h-dvh w-full bg-night">
      <GardenScene
        snapshot={snapshot}
        focus={focus}
        onFocusChange={setFocus}
        matchedConceptIds={matched}
        pulseConceptIds={pulse}
        evidence={evidence}
        onEvidenceSelect={setSelected}
        timeOfDay={hour ?? undefined}
        quality={quality}
        aria-label="Mock learner's skill garden"
      />

      <nav
        aria-label="Garden zoom"
        className="pointer-events-auto absolute left-4 top-4 flex flex-wrap items-center gap-1 rounded-full border border-white/10 bg-night/70 px-3 py-1.5 text-sm backdrop-blur"
      >
        {trail.map((step, i) => (
          <span key={focusToString(step)} className="flex items-center gap-1">
            {i > 0 && <span className="text-foreground/40">/</span>}
            <button
              type="button"
              className={
                i === trail.length - 1
                  ? "font-medium text-glow"
                  : "text-foreground/70 hover:text-foreground"
              }
              onClick={() => setFocus(step)}
            >
              {focusLabel(step, snapshot)}
            </button>
          </span>
        ))}
      </nav>

      <div className="absolute right-4 top-4 flex flex-col items-end gap-2 text-xs">
        <span className="rounded-full border border-bloom/40 bg-night/70 px-3 py-1 text-foreground/70 backdrop-blur">
          Garden lab · mock data
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={simulateLiveGrowth}
            className="rounded-full border border-glow/40 bg-night/70 px-3 py-1.5 text-glow backdrop-blur hover:bg-dusk"
          >
            Simulate live growth
          </button>
          {live && (
            <button
              type="button"
              onClick={() => setLive(null)}
              className="rounded-full border border-white/10 bg-night/70 px-3 py-1.5 backdrop-blur hover:bg-dusk"
            >
              End session
            </button>
          )}
        </div>
        <label className="flex items-center gap-2 rounded-full border border-white/10 bg-night/70 px-3 py-1.5 backdrop-blur">
          <input type="checkbox" checked={onlyDue} onChange={(e) => setOnlyDue(e.target.checked)} />
          Only reviews due
        </label>
        <label className="flex items-center gap-2 rounded-full border border-white/10 bg-night/70 px-3 py-1.5 backdrop-blur">
          Time
          <input
            type="range"
            min={0}
            max={24}
            step={0.25}
            value={hour ?? 12}
            onChange={(e) => setHour(Number(e.target.value))}
            aria-label="Time of day"
          />
          <span className="w-10 tabular-nums">
            {hour === null
              ? "local"
              : `${Math.floor(hour)}:${String(Math.round((hour % 1) * 60)).padStart(2, "0")}`}
          </span>
        </label>
        <label className="flex items-center gap-2 rounded-full border border-white/10 bg-night/70 px-3 py-1.5 backdrop-blur">
          Quality
          <select
            value={quality}
            onChange={(e) => setQuality(e.target.value as GardenQuality)}
            className="bg-transparent"
          >
            <option value="high">High</option>
            <option value="low">Low</option>
          </select>
        </label>
      </div>

      <div className="absolute inset-x-4 bottom-4 mx-auto flex max-w-2xl items-center gap-3 rounded-2xl border border-white/10 bg-night/70 px-4 py-3 text-sm backdrop-blur">
        <button
          type="button"
          onClick={() => {
            if (revision >= MOCK_REVISIONS) setRevision(0);
            setPlaying((p) => !p);
          }}
          className="rounded-full border border-moss/50 px-3 py-1 text-moss hover:bg-dusk"
        >
          {playing ? "Pause" : "Replay"}
        </button>
        <input
          type="range"
          min={0}
          max={MOCK_REVISIONS}
          value={revision}
          onChange={(e) => {
            setPlaying(false);
            setRevision(Number(e.target.value));
          }}
          className="flex-1"
          aria-label="Garden revision"
        />
        <span className="w-28 text-right tabular-nums text-foreground/70">
          rev {revision} ·{" "}
          {new Date(snapshot.createdAt).toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
          })}
        </span>
      </div>

      {selected && (
        <aside className="absolute bottom-24 left-4 w-80 rounded-2xl border border-white/10 bg-night/85 p-4 text-sm backdrop-blur">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-medium capitalize">
              {selected.dimension} · {selected.kind}
            </span>
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="text-foreground/60 hover:text-foreground"
            >
              Close
            </button>
          </div>
          <pre className="whitespace-pre-wrap font-mono text-xs text-foreground/80">
            {selected.excerpt}
          </pre>
          <p className="mt-2 text-xs text-foreground/60">
            {selected.independent ? "Independent" : "Assisted"} · {selected.character} · rubric{" "}
            {selected.rubricVersion} · uncertainty {Math.round(selected.uncertainty * 100)}%
          </p>
        </aside>
      )}
    </div>
  );
}
