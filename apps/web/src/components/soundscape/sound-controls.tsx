"use client";

import { useEffect, useRef } from "react";

import { useSoundscape } from "./soundscape-provider";

/**
 * Sound toggle and volume. Also plays a growth chime when a plant newly appears in
 * `recentGrowthPlantKeys` (not on first render, so opening the page is silent).
 */
export function SoundControls({
  recentGrowthPlantKeys = [],
}: {
  recentGrowthPlantKeys?: string[];
}) {
  const sound = useSoundscape();
  const seen = useRef<Set<string> | null>(null);

  const play = sound?.play;
  useEffect(() => {
    if (!play) return;
    const current = new Set(recentGrowthPlantKeys);
    if (seen.current !== null) {
      for (const key of current) {
        if (!seen.current.has(key)) {
          play({ type: "growth", conceptId: key });
          break; // one chime per update, never a burst
        }
      }
    }
    seen.current = current;
  }, [play, recentGrowthPlantKeys]);

  if (!sound || !sound.ready) return null;
  const on = !sound.muted;
  return (
    <div className="flex items-center gap-2 text-xs text-foreground/70">
      <button
        type="button"
        aria-pressed={on}
        onClick={sound.toggleMuted}
        className="rounded-lg border border-white/10 px-2.5 py-1 outline-none hover:border-white/25 focus-visible:ring-2 focus-visible:ring-glow"
      >
        {on ? "Sound on" : "Sound off"}
      </button>
      {on && (
        <label className="flex items-center gap-1.5">
          <span className="sr-only">Volume</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={sound.volume}
            onChange={(e) => sound.setVolume(Number(e.target.value))}
            aria-label="Volume"
            className="h-1 w-20 accent-glow"
          />
        </label>
      )}
      {on && sound.unavailable && (
        <span role="status" className="text-foreground/50">
          Soundscape not generated yet
        </span>
      )}
      {on && sound.reducedMotion && (
        <span className="text-foreground/50">Quiet mode (reduced motion)</span>
      )}
    </div>
  );
}
