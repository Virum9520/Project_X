/** Recap playback helpers: which keyframe is active at a given time. Pure, so the flythrough can
 * be driven by an <audio> element's `currentTime` or by a silent timer for text-only recaps. */

export interface RecapSegment {
  id: string;
  kind: string;
  text: string;
  /** `garden`, `grove:<id>` or `plant:<concept key>`; the C13 `focusFromString` form. */
  focus: string;
  conceptId?: string | null;
  evidenceIds: string[];
  startMs: number;
  endMs: number;
}

export function segmentAt<T extends Pick<RecapSegment, "startMs" | "endMs">>(
  segments: readonly T[],
  ms: number,
): T | null {
  if (segments.length === 0) return null;
  let found: T | null = null;
  for (const s of segments) {
    if (s.startMs <= ms) found = s;
    else break;
  }
  return found ?? segments[0] ?? null;
}

/** `GET /v1/recap/*` response (camelCase, mirrors `sg_api.recap.schemas.RecapOut`). */
export interface RecapPayload {
  week: string;
  weekStart: string;
  weekEnd: string;
  generatedAt: string;
  narration: string;
  segments: RecapSegment[];
  citations: string[];
  durationMs: number;
  /** aligned: word-accurate; proportional/estimated: approximate. */
  timing: "aligned" | "proportional" | "estimated";
  quiet: boolean;
  rulesVersion: string;
  /** null: a text-only recap (no voice configured or budget spent). */
  audioUrl: string | null;
  shared: boolean;
}

/** `GET /v1/soundscape/manifest` response. */
export interface SoundManifestPayload {
  version: number;
  expiresInSeconds: number;
  assets: { id: string; kind: "music" | "sfx"; url: string; loop?: boolean }[];
}
