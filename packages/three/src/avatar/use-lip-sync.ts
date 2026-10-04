"use client";

import { useMemo } from "react";
import { LipSyncDriver, type LipSyncDriverOptions } from "./lipsync-driver";

/**
 * Stable `LipSyncDriver` for a component. Wire ElevenLabs like:
 *
 * ```ts
 * const lipSync = useLipSync();
 * useConversation({
 *   onAudioAlignment: (a) => lipSync.pushAlignment(a, audioStartMs),
 * });
 * <Avatar driver={lipSync} />
 * ```
 */
export function useLipSync(opts?: LipSyncDriverOptions): LipSyncDriver {
  // Options are read once; the driver is intentionally stable across renders.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => new LipSyncDriver(opts), []);
}
