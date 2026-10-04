"use client";

import { useFrame } from "@react-three/fiber";
import { useRef } from "react";
import type { Group, Mesh } from "three";
import type { LipSyncDriver } from "./lipsync-driver";

export interface ProceduralAvatarProps {
  driver: LipSyncDriver;
  /** Skin/face colour. */
  color?: string;
  /** Accent colour for hair/cap. */
  accent?: string;
}

/**
 * Placeholder avatar built from primitives, used when no `.vrm` asset is configured or loading
 * fails. It consumes the same `LipSyncFrame` as the VRM path, so the pipeline is identical.
 */
export function ProceduralAvatar({
  driver,
  color = "#e8b894",
  accent = "#3b4a7a",
}: ProceduralAvatarProps) {
  const group = useRef<Group>(null);
  const mouth = useRef<Mesh>(null);
  const eyeL = useRef<Mesh>(null);
  const eyeR = useRef<Mesh>(null);
  const pupilL = useRef<Mesh>(null);
  const pupilR = useRef<Mesh>(null);

  useFrame(({ clock }, dt) => {
    const f = driver.frame(undefined, dt);
    const { aa, oh, ou, ee, ih } = f.mouth;
    if (mouth.current) {
      const height = 0.015 + aa * 0.13 + oh * 0.1 + ou * 0.06 + ee * 0.03 + ih * 0.04;
      const width = Math.max(0.05, 0.16 + ee * 0.08 + ih * 0.03 - ou * 0.08 - oh * 0.05);
      mouth.current.scale.set(width, height, 0.05);
    }
    const lid = Math.max(0.08, 1 - f.blink);
    for (const eye of [eyeL.current, eyeR.current]) eye?.scale.set(0.07, 0.07 * lid, 0.04);
    for (const p of [pupilL.current, pupilR.current]) {
      p?.position.set(f.lookX * 0.025, f.lookY * 0.02, 0.035);
      if (p) p.visible = f.blink < 0.6;
    }
    if (group.current) {
      const t = clock.elapsedTime;
      group.current.rotation.y = Math.sin(t * 0.5) * 0.08;
      group.current.position.y = Math.sin(t * 1.3) * 0.01;
    }
  });

  return (
    <group ref={group}>
      <mesh position={[0, 0, 0]}>
        <sphereGeometry args={[0.32, 48, 32]} />
        <meshStandardMaterial color={color} roughness={0.7} />
      </mesh>
      <mesh position={[0, 0.12, -0.02]} scale={[1.04, 0.8, 1.04]}>
        <sphereGeometry args={[0.32, 48, 32, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial color={accent} roughness={0.9} />
      </mesh>
      {[-0.11, 0.11].map((x, i) => (
        <group key={x} position={[x, 0.05, 0.28]}>
          <mesh ref={i === 0 ? eyeL : eyeR} scale={[0.07, 0.07, 0.04]}>
            <sphereGeometry args={[1, 24, 16]} />
            <meshStandardMaterial color="#fdfdfd" />
          </mesh>
          <mesh ref={i === 0 ? pupilL : pupilR} position={[0, 0, 0.035]} scale={0.03}>
            <sphereGeometry args={[1, 16, 12]} />
            <meshStandardMaterial color="#1b1b24" />
          </mesh>
        </group>
      ))}
      <mesh ref={mouth} position={[0, -0.12, 0.3]} scale={[0.16, 0.015, 0.05]}>
        <sphereGeometry args={[1, 24, 16]} />
        <meshStandardMaterial color="#6b1f2a" />
      </mesh>
      <mesh position={[0, -0.5, 0]}>
        <capsuleGeometry args={[0.24, 0.3, 8, 24]} />
        <meshStandardMaterial color={accent} roughness={0.8} />
      </mesh>
    </group>
  );
}
