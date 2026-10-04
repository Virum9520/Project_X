"use client";

import type { LiveGrowthEvent } from "@sg/contracts";
import { useCallback, useEffect, useRef } from "react";

import { INCOMING_CALL_EVENT, createCueSelector } from "@/lib/session/cues";

import { useSoundscape } from "../soundscape/soundscape-provider";

/**
 * Soundscape cues for a voice stage: growth and bloom chimes for live growth events, and the
 * `ring` cue when Bhima's retention call arrives (dispatch `INCOMING_CALL_EVENT` on `window`).
 * Does nothing outside a `SoundscapeProvider`, and the engine itself stays silent until the
 * learner opts in to sound.
 */
export function useSessionCues() {
  const sound = useSoundscape();
  const play = sound?.play;
  const selector = useRef(createCueSelector());

  const onGrowth = useCallback(
    (event: LiveGrowthEvent) => {
      const cue = selector.current.select(event);
      if (cue && play) play(cue);
    },
    [play],
  );
  const reset = useCallback(() => selector.current.reset(), []);

  useEffect(() => {
    if (!play) return;
    const ring = () => play({ type: "ring" });
    window.addEventListener(INCOMING_CALL_EVENT, ring);
    return () => window.removeEventListener(INCOMING_CALL_EVENT, ring);
  }, [play]);

  return { onGrowth, reset };
}
