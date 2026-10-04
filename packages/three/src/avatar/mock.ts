import type { CharAlignment } from "./alignment";

/** Evenly timed fake alignment for demos and tests (real timings come from ElevenLabs). */
export function mockAlignment(text: string, msPerChar = 70): CharAlignment {
  const chars = [...text];
  return {
    chars,
    charStartTimesMs: chars.map((_, i) => i * msPerChar),
    charDurationsMs: chars.map(() => msPerChar),
  };
}
