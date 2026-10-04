"use client";

import type { LipSyncDriver } from "@sg/three/avatar";
import dynamic from "next/dynamic";

/** The avatar is three.js and touches WebGL, so it loads client-side only. */
const AvatarStage = dynamic(() => import("@sg/three/avatar").then((m) => m.AvatarStage), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse bg-dusk/40" />,
});

export function AvatarSlot({ driver, vrmUrl }: { driver: LipSyncDriver; vrmUrl?: string }) {
  return <AvatarStage driver={driver} vrmUrl={vrmUrl} className="h-full w-full" />;
}
