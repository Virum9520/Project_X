/**
 * Frame-time budgets for the garden (C23B). Pure TypeScript, no WebGL: it analyses a list of frame
 * durations that a browser run collected (see `loadtests/frametime/README.md` and
 * `measureFrames`), and holds the static scene-size budget that unit tests enforce in CI.
 */

export interface FrameBudget {
  /** Human name of the device class the budget is for. */
  label: string;
  /** Median frame time, ms. */
  p50Ms: number;
  /** 95th percentile frame time, ms. */
  p95Ms: number;
  /** 99th percentile, ms. */
  p99Ms: number;
  /** Share of frames allowed to exceed 33.3 ms (visible hitches). */
  maxLongFrameShare: number;
}

/** 60 fps target on a desktop with a GPU, 30 fps floor on a mid-range laptop or phone. */
export const FRAME_BUDGETS = {
  desktop: { label: "desktop GPU", p50Ms: 16.7, p95Ms: 22, p99Ms: 33.4, maxLongFrameShare: 0.01 },
  lowEnd: {
    label: "low-end laptop / phone",
    p50Ms: 33.4,
    p95Ms: 45,
    p99Ms: 66.7,
    maxLongFrameShare: 0.05,
  },
} as const satisfies Record<string, FrameBudget>;

export interface FrameStats {
  frames: number;
  meanMs: number;
  p50Ms: number;
  p95Ms: number;
  p99Ms: number;
  maxMs: number;
  longFrameShare: number;
  fps: number;
}

export function percentile(sorted: readonly number[], p: number): number {
  if (sorted.length === 0) return 0;
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil(p * sorted.length) - 1));
  return sorted[idx]!;
}

/** Statistics over frame durations in ms. The first `warmup` frames (shader compile) are dropped. */
export function summarizeFrames(durationsMs: readonly number[], warmup = 30): FrameStats {
  const d = durationsMs.slice(warmup).filter((x) => Number.isFinite(x) && x > 0);
  if (d.length === 0) {
    return {
      frames: 0,
      meanMs: 0,
      p50Ms: 0,
      p95Ms: 0,
      p99Ms: 0,
      maxMs: 0,
      longFrameShare: 0,
      fps: 0,
    };
  }
  const sorted = [...d].sort((a, b) => a - b);
  const mean = d.reduce((a, b) => a + b, 0) / d.length;
  return {
    frames: d.length,
    meanMs: mean,
    p50Ms: percentile(sorted, 0.5),
    p95Ms: percentile(sorted, 0.95),
    p99Ms: percentile(sorted, 0.99),
    maxMs: sorted[sorted.length - 1]!,
    longFrameShare: d.filter((x) => x > 33.3).length / d.length,
    fps: 1000 / mean,
  };
}

/** Violations of a budget, as readable strings. Empty means the run is within budget. */
export function checkFrameBudget(stats: FrameStats, budget: FrameBudget): string[] {
  const out: string[] = [];
  if (stats.frames < 100) out.push(`only ${stats.frames} frames sampled, need at least 100`);
  if (stats.p50Ms > budget.p50Ms) out.push(`p50 ${stats.p50Ms.toFixed(1)} ms > ${budget.p50Ms} ms`);
  if (stats.p95Ms > budget.p95Ms) out.push(`p95 ${stats.p95Ms.toFixed(1)} ms > ${budget.p95Ms} ms`);
  if (stats.p99Ms > budget.p99Ms) out.push(`p99 ${stats.p99Ms.toFixed(1)} ms > ${budget.p99Ms} ms`);
  if (stats.longFrameShare > budget.maxLongFrameShare) {
    out.push(
      `${(stats.longFrameShare * 100).toFixed(1)}% frames over 33 ms > ${(budget.maxLongFrameShare * 100).toFixed(0)}%`,
    );
  }
  return out;
}

/**
 * Static scene budget. These are not frame times, but they bound the work per frame, so a
 * regression that adds geometry fails in CI without a GPU. Numbers come from the current scene
 * (mock garden of ~30 plants, see test/perf-budget.test.ts) with headroom.
 */
export const SCENE_BUDGET = {
  /** Plants in one garden: the curriculum has about 65 concepts. */
  maxPlants: 80,
  /** Vertices of one plant, summed over its parts. */
  maxVerticesPerPlant: 12_000,
  /** Vertices for the whole garden's plants (instancing is not used for plants). */
  maxPlantVerticesTotal: 400_000,
  /** Layout generation for a full garden (CPU, main thread), ms. */
  maxLayoutMs: 50,
} as const;

/**
 * Browser-side probe: call `const stop = measureFrames(); ... const durations = stop();` around a
 * few seconds of interaction (orbiting, zooming). Returns frame durations in ms. Browser only.
 */
export function measureFrames(): () => number[] {
  const durations: number[] = [];
  let last = performance.now();
  let running = true;
  const tick = (now: number) => {
    if (!running) return;
    durations.push(now - last);
    last = now;
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  return () => {
    running = false;
    return durations;
  };
}
