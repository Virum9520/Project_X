"use client";

import type { Character } from "@sg/contracts";
import type { LipSyncDriver } from "@sg/three/avatar";

import { CharacterAvatar } from "@/components/character/character-avatar";

/** The speaker's portrait, pulsing with their voice (the lip-sync driver supplies the level). */
export function AvatarSlot({
  driver,
  character = "drona",
}: {
  driver: LipSyncDriver;
  character?: Character;
  /** Kept for callers that still pass a VRM URL; portraits replaced the 3D avatar. */
  vrmUrl?: string;
}) {
  return (
    <div className="grid h-full w-full place-items-center">
      <CharacterAvatar character={character} size={240} driver={driver} />
    </div>
  );
}
