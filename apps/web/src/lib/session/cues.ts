import type { LiveGrowthEvent } from "@sg/contracts";

/** A one-shot sound the stage should play for a live growth event. */
export type GrowthCue = { type: "growth" | "bloom"; conceptId: string };

/** Window event the Bhima call surface dispatches when a retention call is ringing. */
export const INCOMING_CALL_EVENT = "sg:incoming-call";

/**
 * Chooses the sound for a live growth event. Only independent growth sounds: assisted evidence
 * renders as a ghost part, `noted` and `retracted` events change nothing, and the same
 * concept/part never chimes twice in one session (a confirmation follows its provisional glow).
 */
export function createCueSelector() {
  const played = new Set<string>();
  return {
    select(e: LiveGrowthEvent): GrowthCue | null {
      if (e.assisted || e.part === null) return null;
      if (e.kind !== "provisional" && e.kind !== "confirmed") return null;
      const key = `${e.conceptId}:${e.part}`;
      if (played.has(key)) return null;
      played.add(key);
      return { type: e.part === "blossoms" ? "bloom" : "growth", conceptId: e.conceptId };
    },
    reset() {
      played.clear();
    },
  };
}
