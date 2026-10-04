/** Think-aloud transcript kept beside the editor (live Scribe captions). Never uploaded from here. */

export interface CaptionLine {
  id: number;
  /** Milliseconds since the interview started. */
  atMs: number;
  text: string;
}

export const MAX_CAPTION_LINES = 40;
const MAX_LINE_CHARS = 400;

export function appendCaption(
  lines: readonly CaptionLine[],
  text: string,
  atMs: number,
): CaptionLine[] {
  const clean = text.replace(/\s+/g, " ").trim().slice(0, MAX_LINE_CHARS);
  if (!clean) return [...lines];
  const id = lines.length ? lines[lines.length - 1].id + 1 : 1;
  return [...lines, { id, atMs: Math.max(0, atMs), text: clean }].slice(-MAX_CAPTION_LINES);
}

/** `m:ss` for an offset in milliseconds. */
export function clock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
