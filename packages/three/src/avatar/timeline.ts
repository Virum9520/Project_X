import type { CharAlignment } from "./alignment";
import { alignmentToSegments } from "./alignment";
import { emptyWeights, type VisemeSegment, type VisemeWeights } from "./visemes";

export interface TimelineOptions {
  /** Ramp-in before a segment starts, so the mouth opens ahead of the sound. */
  attackMs: number;
  /** Ramp-out after a segment ends. */
  releaseMs: number;
}

export const DEFAULT_TIMELINE_OPTIONS: TimelineOptions = { attackMs: 35, releaseMs: 70 };

/**
 * An append-only, time-indexed set of viseme segments. Streaming agents deliver alignment in
 * chunks; `append` accepts each chunk with the time (ms since playback started) at which its
 * audio begins.
 */
export class VisemeTimeline {
  private segments: VisemeSegment[] = [];
  private readonly opts: TimelineOptions;
  private maxSpanMs = 0;

  constructor(opts: Partial<TimelineOptions> = {}) {
    this.opts = { ...DEFAULT_TIMELINE_OPTIONS, ...opts };
  }

  get length(): number {
    return this.segments.length;
  }

  /** End of the last segment (ms), or 0 when empty. */
  get endMs(): number {
    let end = 0;
    for (const s of this.segments) end = Math.max(end, s.endMs);
    return end;
  }

  append(alignment: CharAlignment, audioStartMs = 0): void {
    this.addSegments(alignmentToSegments(alignment, audioStartMs));
  }

  addSegments(segs: readonly VisemeSegment[]): void {
    for (const s of segs) {
      this.segments.push(s);
      this.maxSpanMs = Math.max(this.maxSpanMs, s.endMs - s.startMs);
    }
    this.segments.sort((a, b) => a.startMs - b.startMs);
  }

  clear(): void {
    this.segments = [];
    this.maxSpanMs = 0;
  }

  /** True when any segment is audible or ramping at `tMs`. */
  isActive(tMs: number): boolean {
    return this.sampleInto(tMs, emptyWeights());
  }

  /** Weights at time `tMs`. Overlapping shapes combine by max, so the mouth never over-opens. */
  sample(tMs: number): VisemeWeights {
    const w = emptyWeights();
    this.sampleInto(tMs, w);
    return w;
  }

  private sampleInto(tMs: number, out: VisemeWeights): boolean {
    const { attackMs, releaseMs } = this.opts;
    // Segments are sorted by start. Anything starting after tMs + attack cannot contribute.
    const earliest = tMs - releaseMs - this.maxSpanMs;
    let active = false;
    for (let i = this.upperBound(tMs + attackMs) - 1; i >= 0; i--) {
      const s = this.segments[i];
      if (!s) continue;
      if (s.startMs < earliest) break;
      const level = envelope(s, tMs, attackMs, releaseMs);
      if (level > 0) {
        active = true;
        if (level > out[s.viseme]) out[s.viseme] = level;
      }
    }
    return active;
  }

  /** Index of the first segment with startMs > t. */
  private upperBound(t: number): number {
    let lo = 0;
    let hi = this.segments.length;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if ((this.segments[mid]?.startMs ?? 0) <= t) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }
}

function envelope(s: VisemeSegment, t: number, attackMs: number, releaseMs: number): number {
  if (t < s.startMs - attackMs || t > s.endMs + releaseMs) return 0;
  if (t < s.startMs) return s.weight * smooth((t - (s.startMs - attackMs)) / attackMs);
  if (t <= s.endMs) return s.weight;
  return s.weight * smooth(1 - (t - s.endMs) / releaseMs);
}

function smooth(x: number): number {
  const c = Math.min(1, Math.max(0, x));
  return c * c * (3 - 2 * c);
}
