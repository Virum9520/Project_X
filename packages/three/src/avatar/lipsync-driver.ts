import type { CharAlignment } from "./alignment";
import { createIdleAnimator, type IdleAnimator } from "./idle";
import { VisemeTimeline, type TimelineOptions } from "./timeline";
import { emptyWeights, MOUTH_VISEMES, type VisemeWeights } from "./visemes";

export interface LipSyncFrame {
  mouth: VisemeWeights;
  blink: number;
  lookX: number;
  lookY: number;
  /** True while alignment (or the level fallback) is driving the mouth. */
  speaking: boolean;
}

export interface LipSyncDriverOptions {
  now?: () => number;
  timeline?: Partial<TimelineOptions>;
  seed?: number;
  /** Mouth smoothing speed (1/s). Higher is snappier. */
  smoothing?: number;
}

/**
 * Framework-free lip-sync state machine. Feed it `onAudioAlignment` chunks plus the playback
 * origin, then call `frame(now, dt)` every render tick and apply the result to a rig.
 *
 * Timing model: alignment times are relative to the start of each audio chunk. The caller passes
 * `audioStartMs`, the time in the utterance (ms since `start()`) at which that chunk begins. For a
 * single-shot TTS response that is simply 0.
 *
 * If no alignment is active, `setLevel(0..1)` (e.g. from output frequency/volume data) opens the
 * mouth as a fallback.
 */
export class LipSyncDriver {
  private readonly timeline: VisemeTimeline;
  private readonly idle: IdleAnimator;
  private readonly now: () => number;
  private readonly smoothing: number;
  private originMs: number | null = null;
  private level = 0;
  private current: VisemeWeights = emptyWeights();

  constructor(opts: LipSyncDriverOptions = {}) {
    this.now = opts.now ?? (() => performance.now());
    this.timeline = new VisemeTimeline(opts.timeline);
    this.idle = createIdleAnimator(opts.seed ?? 1);
    this.smoothing = opts.smoothing ?? 30;
  }

  /** Mark playback time zero. Called automatically by the first `pushAlignment`. */
  start(atMs: number = this.now()): void {
    this.originMs = atMs;
  }

  pushAlignment(alignment: CharAlignment, audioStartMs = 0): void {
    if (this.originMs === null) this.start();
    this.timeline.append(alignment, audioStartMs);
  }

  setLevel(level: number): void {
    this.level = Math.min(1, Math.max(0, level));
  }

  /** Drop all queued alignment (interruption, new utterance). */
  reset(): void {
    this.timeline.clear();
    this.originMs = null;
    this.level = 0;
  }

  frame(nowMs: number = this.now(), dtSec = 1 / 60): LipSyncFrame {
    const target = emptyWeights();
    let speaking = false;
    if (this.originMs !== null && this.timeline.length > 0) {
      const t = nowMs - this.originMs;
      speaking = this.timeline.isActive(t);
      if (speaking) Object.assign(target, this.timeline.sample(t));
    }
    if (!speaking && this.level > 0.02) {
      speaking = true;
      target.aa = this.level * 0.8;
      target.oh = this.level * 0.2;
    }

    const k = 1 - Math.exp(-Math.max(0, dtSec) * this.smoothing);
    for (const v of MOUTH_VISEMES) {
      this.current[v] += (target[v] - this.current[v]) * k;
    }
    const idle = this.idle.update(dtSec);
    return { mouth: { ...this.current }, speaking, ...idle };
  }
}
