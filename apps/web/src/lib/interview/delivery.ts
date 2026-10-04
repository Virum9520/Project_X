/**
 * Optional delivery observations, computed entirely in the browser and only when the learner
 * opts in: how much of the time their face was in frame, how much they faced the camera, and
 * their speaking pace. Only three aggregate numbers ever leave the browser (see
 * `DeliverySummary` in the API, which rejects anything else). Frames are sampled and discarded.
 *
 * These describe delivery, never honesty, personality, emotion or competence, and nothing here
 * infers them. Gaze is approximated by head orientation toward the camera, not eye tracking.
 */

export interface FaceSample {
  /** Normalised 0..1 bounding box of the detected face in the frame; null when none found. */
  box: { x: number; y: number; w: number; h: number } | null;
  /** Head turn proxy in -1..1 (0 = straight at the camera); null when unknown. */
  yaw: number | null;
}

export const FRAMING = {
  minHeight: 0.2,
  maxHeight: 0.85,
  margin: 0.02,
  centre: [0.2, 0.8],
} as const;
export const FACING_YAW = 0.25;
export const MIN_SAMPLES = 10;

export function classifyFrame(sample: FaceSample): { framed: boolean; facing: boolean } {
  const b = sample.box;
  if (!b) return { framed: false, facing: false };
  const cx = b.x + b.w / 2;
  const cy = b.y + b.h / 2;
  const inside =
    b.x >= FRAMING.margin &&
    b.y >= FRAMING.margin &&
    b.x + b.w <= 1 - FRAMING.margin &&
    b.y + b.h <= 1 - FRAMING.margin;
  const framed =
    inside &&
    b.h >= FRAMING.minHeight &&
    b.h <= FRAMING.maxHeight &&
    cx >= FRAMING.centre[0] &&
    cx <= FRAMING.centre[1] &&
    cy >= FRAMING.centre[0] &&
    cy <= FRAMING.centre[1];
  const facing = sample.yaw !== null && Math.abs(sample.yaw) <= FACING_YAW;
  return { framed, facing };
}

/** Bounding box and head-turn proxy from MediaPipe face landmarks (468-point mesh). */
export function sampleFromLandmarks(landmarks: readonly { x: number; y: number }[]): FaceSample {
  if (landmarks.length < 455) return { box: null, yaw: null };
  let minX = 1;
  let minY = 1;
  let maxX = 0;
  let maxY = 0;
  for (const p of landmarks) {
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x);
    maxY = Math.max(maxY, p.y);
  }
  const nose = landmarks[1];
  const left = landmarks[234];
  const right = landmarks[454];
  const span = right.x - left.x;
  const yaw = Math.abs(span) < 1e-6 ? null : ((nose.x - left.x) / span - 0.5) * 2;
  return { box: { x: minX, y: minY, w: maxX - minX, h: maxY - minY }, yaw };
}

export interface DeliverySummary {
  consent: true;
  duration_s: number;
  samples: number;
  framing_ratio: number;
  gaze_ratio: number;
  pace_wpm: number | null;
}

const round = (n: number, places = 3) => Number(n.toFixed(places));

export class DeliveryAccumulator {
  private samples = 0;
  private framed = 0;
  private facing = 0;

  add(sample: FaceSample): void {
    const c = classifyFrame(sample);
    this.samples += 1;
    if (c.framed) this.framed += 1;
    if (c.facing) this.facing += 1;
  }

  get count(): number {
    return this.samples;
  }

  /** Null when there are too few samples to say anything. */
  summary(durationS: number, paceWpm: number | null): DeliverySummary | null {
    if (this.samples < MIN_SAMPLES || !(durationS > 0)) return null;
    return {
      consent: true,
      duration_s: round(Math.min(durationS, 7200), 1),
      samples: this.samples,
      framing_ratio: round(this.framed / this.samples),
      gaze_ratio: round(this.facing / this.samples),
      pace_wpm: paceWpm === null ? null : round(Math.min(Math.max(paceWpm, 0), 400), 1),
    };
  }
}

export const countWords = (text: string) => text.trim().split(/\s+/).filter(Boolean).length;

/**
 * Speaking pace from transcript timing: words of each learner answer divided by the time between
 * the interviewer finishing and the answer arriving. That window includes thinking pauses, so
 * it is a conservative pace, and windows over three minutes or under 1.5 s are ignored.
 */
export class PaceTracker {
  private words = 0;
  private seconds = 0;
  private listeningSince: number | null = null;

  markListening(nowMs: number): void {
    this.listeningSince = nowMs;
  }

  onLearnerMessage(text: string, nowMs: number): void {
    const start = this.listeningSince;
    this.listeningSince = null;
    if (start === null) return;
    const seconds = (nowMs - start) / 1000;
    if (seconds < 1.5 || seconds > 180) return;
    this.words += countWords(text);
    this.seconds += seconds;
  }

  get wpm(): number | null {
    return this.seconds >= 10 && this.words > 0 ? (this.words / this.seconds) * 60 : null;
  }
}
