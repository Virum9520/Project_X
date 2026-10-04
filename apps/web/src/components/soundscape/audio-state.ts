import type { GardenAudioState } from "@sg/audio";
import { useMemo } from "react";

/** The slice of the garden the soundscape mixes from (plant stages and wilting). */
export function useGardenAudioState(
  plants: readonly { stage: string; wilting: boolean }[],
): GardenAudioState {
  return useMemo(
    () => ({ plants: plants.map((p) => ({ stage: p.stage, wilting: p.wilting })) }),
    [plants],
  );
}
