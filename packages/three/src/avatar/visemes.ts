/** The five VRM mouth presets we drive (`aa ih ou ee oh`). Silence means a closed mouth. */
export const MOUTH_VISEMES = ["aa", "ih", "ou", "ee", "oh"] as const;
export type MouthViseme = (typeof MOUTH_VISEMES)[number];

export type VisemeWeights = Record<MouthViseme, number>;

export function emptyWeights(): VisemeWeights {
  return { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
}

/** One mouth shape held over a time span (milliseconds from the start of the utterance). */
export interface VisemeSegment {
  startMs: number;
  endMs: number;
  viseme: MouthViseme;
  /** Peak openness, 0..1. Vowels are near 1, consonants are weaker shapes. */
  weight: number;
}
