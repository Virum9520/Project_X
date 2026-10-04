import type { MouthViseme, VisemeSegment } from "./visemes";

/**
 * Character timings as ElevenLabs reports them to `onAudioAlignment` (Conversational AI SDK) and
 * as the TTS `with-timestamps` endpoint returns them (after `fromTtsTimestamps`).
 */
export interface CharAlignment {
  chars: readonly string[];
  charStartTimesMs: readonly number[];
  charDurationsMs: readonly number[];
}

/** Shape of the REST `/text-to-speech/{voice}/with-timestamps` alignment object. */
export interface TtsTimestampAlignment {
  characters: readonly string[];
  character_start_times_seconds: readonly number[];
  character_end_times_seconds: readonly number[];
}

export function fromTtsTimestamps(a: TtsTimestampAlignment): CharAlignment {
  return {
    chars: a.characters,
    charStartTimesMs: a.character_start_times_seconds.map((s) => s * 1000),
    charDurationsMs: a.character_end_times_seconds.map((e, i) => {
      const start = a.character_start_times_seconds[i] ?? e;
      return Math.max(0, (e - start) * 1000);
    }),
  };
}

const VOWELS: Record<string, MouthViseme> = {
  a: "aa",
  e: "ee",
  i: "ih",
  o: "oh",
  u: "ou",
  y: "ih",
};

/** Digraphs that sound like a single vowel. Checked before single letters. */
const DIGRAPHS: Record<string, MouthViseme> = {
  oo: "ou",
  ou: "ou",
  ow: "ou",
  ee: "ee",
  ea: "ee",
  ie: "ee",
  ai: "ee",
  ay: "ee",
  oa: "oh",
  oi: "oh",
  au: "aa",
  aw: "aa",
};

/** Consonants: a weak shape, or null for a closed mouth (lips pressed). */
const CONSONANTS: Record<string, { viseme: MouthViseme; weight: number } | null> = {
  b: null,
  m: null,
  p: null,
  f: { viseme: "ih", weight: 0.25 },
  v: { viseme: "ih", weight: 0.25 },
  w: { viseme: "ou", weight: 0.6 },
  q: { viseme: "ou", weight: 0.5 },
  r: { viseme: "ou", weight: 0.35 },
  l: { viseme: "ee", weight: 0.3 },
  s: { viseme: "ee", weight: 0.25 },
  z: { viseme: "ee", weight: 0.25 },
  c: { viseme: "ee", weight: 0.25 },
  x: { viseme: "ee", weight: 0.25 },
  j: { viseme: "ih", weight: 0.3 },
  t: { viseme: "ih", weight: 0.2 },
  d: { viseme: "ih", weight: 0.2 },
  n: { viseme: "ih", weight: 0.2 },
  k: { viseme: "ih", weight: 0.25 },
  g: { viseme: "ih", weight: 0.25 },
  h: { viseme: "aa", weight: 0.2 },
};

const VOWEL_WEIGHT = 0.9;
const DIGRAPH_WEIGHT = 0.9;

function foldChar(ch: string): string {
  // Strip diacritics so "é" maps like "e". Non-letters fall through unchanged.
  return ch.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/**
 * Map character timings to mouth-shape segments. Pure and deterministic.
 * Whitespace, punctuation and unknown characters produce no segment (mouth closes).
 * Bilabials (b, m, p) also produce none, which gives the natural lip closure.
 */
export function alignmentToSegments(alignment: CharAlignment, offsetMs = 0): VisemeSegment[] {
  const n = Math.min(
    alignment.chars.length,
    alignment.charStartTimesMs.length,
    alignment.charDurationsMs.length,
  );
  const folded: string[] = [];
  for (let i = 0; i < n; i++) folded.push(foldChar(alignment.chars[i] ?? ""));

  const out: VisemeSegment[] = [];
  const push = (startIdx: number, endIdx: number, viseme: MouthViseme, weight: number) => {
    const startMs = (alignment.charStartTimesMs[startIdx] ?? 0) + offsetMs;
    const lastStart = alignment.charStartTimesMs[endIdx] ?? 0;
    const lastDur = alignment.charDurationsMs[endIdx] ?? 0;
    const endMs = Math.max(startMs, lastStart + lastDur + offsetMs);
    out.push({ startMs, endMs, viseme, weight });
  };

  for (let i = 0; i < n; i++) {
    const ch = folded[i] ?? "";
    const next = folded[i + 1];
    if (next !== undefined && ch.length === 1 && next.length === 1) {
      const pair = DIGRAPHS[ch + next];
      if (pair) {
        push(i, i + 1, pair, DIGRAPH_WEIGHT);
        i++;
        continue;
      }
    }
    const vowel = VOWELS[ch];
    if (vowel) {
      push(i, i, vowel, VOWEL_WEIGHT);
      continue;
    }
    const cons = CONSONANTS[ch];
    if (cons) push(i, i, cons.viseme, cons.weight);
  }
  return out;
}
