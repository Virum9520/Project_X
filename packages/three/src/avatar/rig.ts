import type { LipSyncFrame } from "./lipsync-driver";

/** Anything that can show a lip-sync frame: a VRM model or the procedural fallback. */
export interface AvatarRig {
  apply(frame: LipSyncFrame, dtSec: number): void;
}
