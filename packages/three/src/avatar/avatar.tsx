"use client";

import { Canvas } from "@react-three/fiber";
import { useState } from "react";
import type { LipSyncDriver } from "./lipsync-driver";
import { ProceduralAvatar } from "./procedural-avatar";
import { VrmAvatar } from "./vrm-avatar";

export interface AvatarProps {
  driver: LipSyncDriver;
  /** Optional `.vrm` URL. Without it, or if loading fails, a procedural placeholder is shown. */
  vrmUrl?: string;
  color?: string;
  accent?: string;
}

/** Render inside an R3F `<Canvas>`. */
export function Avatar({ driver, vrmUrl, color, accent }: AvatarProps) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  if (vrmUrl && failedUrl !== vrmUrl) {
    return <VrmAvatar url={vrmUrl} driver={driver} onError={() => setFailedUrl(vrmUrl)} />;
  }
  return <ProceduralAvatar driver={driver} color={color} accent={accent} />;
}

/** Self-contained canvas with lights and camera framing for a head-and-shoulders avatar. */
export function AvatarStage({ className, ...props }: AvatarProps & { className?: string }) {
  return (
    <Canvas className={className} camera={{ position: [0, 0.1, 1.6], fov: 30 }} dpr={[1, 2]}>
      <ambientLight intensity={0.8} />
      <directionalLight position={[1.5, 2, 2]} intensity={1.8} />
      <Avatar {...props} />
    </Canvas>
  );
}
