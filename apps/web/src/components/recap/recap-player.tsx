"use client";

import type { GardenDataset, FocusTarget } from "@sg/contracts";
import { type RecapPayload, segmentAt } from "@sg/audio";
import { useEffect, useMemo, useRef, useState, useTransition } from "react";

import { generateRecap, shareRecap, unshareRecap } from "@/app/(app)/recap/actions";
import { cutoffMs, plantsAt } from "@/lib/garden/derive";
import { DEFAULT_STATE } from "@/lib/garden/state";

import { GardenSceneSlot } from "../garden/garden-scene-slot";
import { useSoundscape } from "../soundscape/soundscape-provider";
import { SoundscapeProvider } from "../soundscape/soundscape-provider";

/** `plant:dsa.graphs` / `grove:dsa` / `garden`, the C13 `focusToString` form. */
function focusFromRecap(value: string): FocusTarget {
  if (value.startsWith("plant:")) return { level: "plant", plantKey: value.slice(6) };
  if (value.startsWith("grove:"))
    return {
      level: "grove",
      groveId: value.slice(6) as Extract<FocusTarget, { level: "grove" }>["groveId"],
    };
  return { level: "garden" };
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const q = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(q.matches);
    update();
    q.addEventListener("change", update);
    return () => q.removeEventListener("change", update);
  }, []);
  return reduced;
}

export function RecapPlayer({
  dataset,
  initial,
}: {
  dataset: GardenDataset;
  initial: RecapPayload | null;
}) {
  const [recap, setRecap] = useState(initial);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const [sharePath, setSharePath] = useState<string | null>(null);

  const state = DEFAULT_STATE;
  const cutoff = useMemo(() => cutoffMs(dataset, null, state.filters), [dataset, state.filters]);
  const plants = useMemo(
    () => plantsAt(dataset, state.filters, cutoff),
    [dataset, state.filters, cutoff],
  );
  const audioState = useMemo(
    () => ({ plants: plants.map((p) => ({ stage: p.stage, wilting: p.wilting })) }),
    [plants],
  );

  return (
    <SoundscapeProvider garden={audioState}>
      <main className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col gap-4 px-4 pb-16 pt-24 sm:px-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-glow">Weekly recap</p>
            <h1 className="mt-1 text-2xl font-semibold sm:text-3xl">Your week, told by Sanjaya</h1>
          </div>
          <button
            type="button"
            disabled={pending}
            onClick={() =>
              startTransition(async () => {
                setMessage(null);
                const result = await generateRecap(Boolean(recap));
                if (result.ok) setRecap(result.data);
                else setMessage(result.message);
              })
            }
            className="rounded-lg bg-glow/20 px-3 py-1.5 text-sm text-glow outline-none hover:bg-glow/30 focus-visible:ring-2 focus-visible:ring-glow disabled:opacity-50"
          >
            {pending
              ? "Writing…"
              : recap
                ? "Rebuild this week's recap"
                : "Create this week's recap"}
          </button>
        </header>
        {message && (
          <p role="alert" className="rounded-xl bg-ember/15 px-4 py-2 text-sm text-ember">
            {message}
          </p>
        )}
        {recap ? (
          <Flythrough
            recap={recap}
            plants={plants}
            dataset={dataset}
            cutoff={cutoff}
            sharePath={sharePath}
            onShare={() =>
              startTransition(async () => {
                const result = await shareRecap(recap.week);
                if (result.ok) {
                  setSharePath(result.data.path);
                  setRecap({ ...recap, shared: true });
                } else setMessage(result.message);
              })
            }
            onUnshare={() =>
              startTransition(async () => {
                const result = await unshareRecap(recap.week);
                if (result.ok) {
                  setSharePath(null);
                  setRecap({ ...recap, shared: false });
                } else setMessage(result.message);
              })
            }
          />
        ) : (
          <p className="text-foreground/70">
            No recap yet. Create one to hear what grew this week and what to practise next.
          </p>
        )}
      </main>
    </SoundscapeProvider>
  );
}

function Flythrough({
  recap,
  plants,
  dataset,
  cutoff,
  sharePath,
  onShare,
  onUnshare,
}: {
  recap: RecapPayload;
  plants: ReturnType<typeof plantsAt>;
  dataset: GardenDataset;
  cutoff: number;
  sharePath: string | null;
  onShare: () => void;
  onUnshare: () => void;
}) {
  const reducedMotion = usePrefersReducedMotion();
  const sound = useSoundscape();
  const audioRef = useRef<HTMLAudioElement>(null);
  const [ms, setMs] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [step, setStep] = useState(0);

  // Silent (text-only) recaps and reduced motion both drive the camera from a timer or buttons.
  const hasAudio = recap.audioUrl !== null;
  const timerMode = !hasAudio && !reducedMotion;
  useEffect(() => {
    if (!timerMode || !playing) return;
    const started = performance.now() - ms;
    const id = window.setInterval(() => {
      const t = performance.now() - started;
      if (t >= recap.durationMs) {
        setPlaying(false);
        setMs(recap.durationMs);
      } else setMs(t);
    }, 200);
    return () => window.clearInterval(id);
    // `ms` is read once at start so resuming continues where it paused.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timerMode, playing, recap.durationMs]);

  const active = reducedMotion ? (recap.segments[step] ?? null) : segmentAt(recap.segments, ms);
  const focus = useMemo(
    () => (active ? focusFromRecap(active.focus) : ({ level: "garden" } as FocusTarget)),
    [active],
  );
  const evidenceCount = recap.citations.length;

  return (
    <section className="flex flex-col gap-3" aria-label="Recap flythrough">
      <GardenSceneSlot
        groves={dataset.groves}
        plants={plants}
        focus={focus}
        onFocusChange={() => {}}
        asOf={new Date(cutoff).toISOString()}
        isTimeTravel={false}
        recentGrowthPlantKeys={active?.conceptId ? [active.conceptId] : []}
        evidence={dataset.evidence}
        prerequisites={dataset.prerequisites}
        revision={dataset.growthEvents.reduce((m, g) => Math.max(m, g.revision), 0)}
        ruleVersion={recap.rulesVersion}
      />
      <div className="flex flex-wrap items-center gap-3">
        {hasAudio ? (
          <audio
            ref={audioRef}
            src={recap.audioUrl ?? undefined}
            controls
            preload="none"
            className="h-9 max-w-full"
            onPlay={() => sound?.play({ type: "recap_start" })}
            onTimeUpdate={(e) => setMs(e.currentTarget.currentTime * 1000)}
          />
        ) : timerMode ? (
          <button
            type="button"
            onClick={() => {
              if (ms >= recap.durationMs) setMs(0);
              setPlaying((p) => !p);
            }}
            className="rounded-lg border border-white/10 px-3 py-1 text-sm outline-none hover:border-white/25 focus-visible:ring-2 focus-visible:ring-glow"
          >
            {playing ? "Pause" : "Play captions and camera"}
          </button>
        ) : null}
        {reducedMotion && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-foreground/60">Camera moves only when you step:</span>
            <button
              type="button"
              disabled={step === 0}
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              className="rounded-lg border border-white/10 px-2.5 py-1 disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={step >= recap.segments.length - 1}
              onClick={() => setStep((s) => Math.min(recap.segments.length - 1, s + 1))}
              className="rounded-lg border border-white/10 px-2.5 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        )}
        <span className="text-xs text-foreground/50">
          {recap.week} · {evidenceCount} evidence {evidenceCount === 1 ? "citation" : "citations"}
          {recap.timing !== "aligned" && hasAudio ? " · camera timing approximate" : ""}
          {!hasAudio ? " · text recap" : ""}
        </span>
      </div>

      <ol className="flex flex-col gap-2" aria-label="Recap transcript">
        {recap.segments.map((s) => (
          <li
            key={s.id}
            aria-current={active?.id === s.id ? "true" : undefined}
            className={`rounded-xl px-4 py-2 text-sm ${
              active?.id === s.id ? "bg-glow/15 text-foreground" : "bg-white/5 text-foreground/70"
            }`}
          >
            {s.text}
            {s.evidenceIds.length > 0 && (
              <span className="ml-2 text-xs text-foreground/50">
                Evidence: {s.evidenceIds.length}
              </span>
            )}
          </li>
        ))}
      </ol>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        {recap.shared ? (
          <>
            <span className="text-foreground/70">
              {sharePath ? `Private link: ${sharePath}` : "A private link is active."}
            </span>
            <button
              type="button"
              onClick={onUnshare}
              className="rounded-lg border border-white/10 px-2.5 py-1 hover:border-white/25"
            >
              Turn link off
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={onShare}
            className="rounded-lg border border-white/10 px-2.5 py-1 hover:border-white/25"
          >
            Create private link
          </button>
        )}
      </div>
    </section>
  );
}
