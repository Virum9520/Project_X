/**
 * Panel voice tags. The Panel agent speaks as two interviewers in one conversation (ADR 0002):
 * Arjuna's lines are wrapped in `<Arjuna>…</Arjuna>`, everything else is Vidura. The browser
 * needs to know who is talking to cut the camera, and must never show the raw tags in captions.
 *
 * Everything here is pure and defensive: the text is model output, so tags may be unclosed
 * (streaming), nested wrongly or unknown.
 */

export type PanelSpeaker = "vidura" | "arjuna";

export interface SpeakerSegment {
  speaker: PanelSpeaker;
  text: string;
}

const TAG = /<\s*(\/?)\s*([A-Za-z]{1,16})\s*>/g;
const SPEAKERS: Record<string, PanelSpeaker> = { vidura: "vidura", arjuna: "arjuna" };

/** Split a (possibly partial) agent message into per-speaker segments. Unknown tags are dropped. */
export function parseVoiceTags(raw: string): SpeakerSegment[] {
  const segments: SpeakerSegment[] = [];
  let current: PanelSpeaker = "vidura";
  let last = 0;
  const push = (end: number) => {
    const text = raw.slice(last, end).replace(/\s+/g, " ").trim();
    if (text) segments.push({ speaker: current, text });
  };
  for (const match of raw.matchAll(TAG)) {
    push(match.index);
    last = match.index + match[0].length;
    const named = SPEAKERS[match[2].toLowerCase()];
    if (named) current = match[1] ? "vidura" : named;
  }
  push(raw.length);
  return segments;
}

/** The message with tags removed, for captions. */
export function plainText(raw: string): string {
  return parseVoiceTags(raw)
    .map((s) => s.text)
    .join(" ");
}

/** Who is speaking at the end of a message: the last segment's speaker. */
export function lastSpeaker(raw: string, fallback: PanelSpeaker = "vidura"): PanelSpeaker {
  const segments = parseVoiceTags(raw);
  return segments.length ? segments[segments.length - 1].speaker : fallback;
}

/**
 * Speaker for an ElevenLabs message payload. Prefers an explicit voice label if the payload
 * carries one (to be confirmed live, ADR 0002), otherwise reads the tags in the text.
 */
export function speakerOfMessage(
  payload: unknown,
  fallback: PanelSpeaker = "vidura",
): PanelSpeaker {
  if (payload && typeof payload === "object") {
    const p = payload as Record<string, unknown>;
    const label = p.voice_label ?? p.voiceLabel;
    if (typeof label === "string" && SPEAKERS[label.toLowerCase()])
      return SPEAKERS[label.toLowerCase()];
    if (typeof p.message === "string") return lastSpeaker(p.message, fallback);
  }
  return fallback;
}
