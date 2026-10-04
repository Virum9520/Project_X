"use client";

import type { PlantPart, PlantSnapshot } from "@sg/contracts";
import { useCursor } from "@react-three/drei";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { memo, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

import type { PlantLayout } from "../generator/layout";
import { PLANT_PARTS, plantGrowth, type PartGrowth } from "../model/growth";
import { buildPlantShape } from "./plantGeometry";
import { createPlantMaterial, createPlantUniforms, type PlantUniforms } from "./plantMaterial";

export type PlantInteraction = "plant" | "parts" | "none";

export interface PlantProps {
  plant: PlantSnapshot;
  layout: PlantLayout;
  groveColor: string;
  dimmed: boolean;
  pulsing: boolean;
  /** Seconds to wait before growing in on first mount. */
  introDelay: number;
  interaction: PlantInteraction;
  focusedPart: PlantPart | null;
  onSelect: (conceptId: string) => void;
  onSelectPart: (conceptId: string, part: PlantPart) => void;
}

/** How quickly growth eases toward a new revision (higher is faster). */
const GROWTH_LAMBDA = 1.8;
let blobTexture: THREE.Texture | null = null;
/** Soft radial contact shadow, shared by every plant. */
function getBlobTexture(): THREE.Texture {
  if (blobTexture) return blobTexture;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 64;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
    g.addColorStop(0, "rgba(0,0,0,0.55)");
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 64, 64);
  }
  blobTexture = new THREE.CanvasTexture(canvas);
  return blobTexture;
}

function PlantImpl({
  plant,
  layout,
  groveColor,
  dimmed,
  pulsing,
  introDelay,
  interaction,
  focusedPart,
  onSelect,
  onSelectPart,
}: PlantProps) {
  const growth = useMemo(() => plantGrowth(plant), [plant]);
  const shape = useMemo(
    () => buildPlantShape(layout.seed, { grove: groveColor }),
    [layout.seed, groveColor],
  );
  const { uniforms, materials } = useMemo(() => {
    const phase = (layout.seed % 1000) / 159;
    const droop = layout.rotation + 1.3;
    const uniforms = Object.fromEntries(
      PLANT_PARTS.map((part) => [part, createPlantUniforms(shape.height, phase, droop)]),
    ) as Record<PlantPart, PlantUniforms>;
    uniforms.roots.uSway.value = 0;
    const materials = Object.fromEntries(
      PLANT_PARTS.map((part) => [
        part,
        createPlantMaterial(uniforms[part], {
          roughness: part === "blossoms" ? 0.5 : 0.75,
          // Roots and blossoms carry a faint warm glow so the dimensions read at a distance.
          emissive: part === "roots" ? "#d39a5c" : part === "blossoms" ? "#f4b8d4" : "#000000",
          emissiveIntensity: part === "roots" ? 0.18 : part === "blossoms" ? 0.22 : 0,
        }),
      ]),
    ) as Record<PlantPart, THREE.MeshStandardMaterial>;
    return { uniforms, materials };
  }, [shape, layout.seed, layout.rotation]);

  useEffect(
    () => () => {
      for (const part of PLANT_PARTS) {
        shape.parts[part].dispose();
        materials[part].dispose();
      }
    },
    [shape, materials],
  );

  const [hovered, setHovered] = useState<PlantPart | "plant" | null>(null);
  useCursor(hovered !== null && interaction !== "none");

  // Animated state, eased toward the target growth every frame (growth between revisions).
  const anim = useRef({
    parts: Object.fromEntries(
      PLANT_PARTS.map((p) => [p, { solid: 0, confirmed: 0, total: 0 }]),
    ) as Record<PlantPart, PartGrowth>,
    wilt: 0,
    dim: 0,
    glow: 0,
    seed: 1,
  });
  const seedRef = useRef<THREE.Mesh>(null);

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime;
    const a = anim.current;
    const dt = Math.min(delta, 0.1);
    const started = t >= introDelay;
    for (const part of PLANT_PARTS) {
      const target = growth.parts[part];
      const cur = a.parts[part];
      cur.solid = THREE.MathUtils.damp(cur.solid, started ? target.solid : 0, GROWTH_LAMBDA, dt);
      cur.confirmed = THREE.MathUtils.damp(
        cur.confirmed,
        started ? target.confirmed : 0,
        GROWTH_LAMBDA,
        dt,
      );
      cur.total = THREE.MathUtils.damp(cur.total, started ? target.total : 0, GROWTH_LAMBDA, dt);
    }
    a.wilt = THREE.MathUtils.damp(a.wilt, started ? growth.wilt : 0, 1.2, dt);
    a.dim = THREE.MathUtils.damp(a.dim, dimmed ? 1 : 0, 4, dt);
    const glowTarget = pulsing ? 0.6 + 0.6 * Math.sin(t * 3) : hovered ? 0.35 : 0;
    a.glow = THREE.MathUtils.damp(a.glow, glowTarget, 6, dt);
    a.seed = THREE.MathUtils.damp(a.seed, growth.dormant || !started ? 1 : 0.0001, 2, dt);

    for (const part of PLANT_PARTS) {
      const u = uniforms[part];
      const g = a.parts[part];
      u.uGrowth.value = g.total;
      u.uSolid.value = g.solid;
      u.uConfirmed.value = g.confirmed;
      u.uParent.value =
        part === "branches" || part === "blossoms" ? Math.max(a.parts.stem.total, 0.0001) : 1;
      u.uWilt.value = part === "roots" ? 0 : a.wilt;
      u.uOpen.value = part === "blossoms" ? 1 - 0.45 * a.wilt : 1;
      u.uDim.value = a.dim;
      u.uGlow.value = a.glow + (focusedPart === part ? 0.5 + 0.3 * Math.sin(t * 2.5) : 0);
      u.uTime.value = t;
    }
    if (seedRef.current) seedRef.current.scale.setScalar(a.seed);
  });

  const select = (event: ThreeEvent<MouseEvent>, part?: PlantPart) => {
    event.stopPropagation();
    if (part) onSelectPart(plant.conceptId, part);
    else onSelect(plant.conceptId);
  };
  const hover = (target: PlantPart | "plant" | null) => (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    setHovered(target);
  };

  const h = shape.height;
  const stemTop = h * Math.max(growth.parts.stem.total, 0.22);
  const [x, y, z] = layout.position;

  return (
    <group position={[x, y, z]} rotation-y={layout.rotation} scale={layout.scale}>
      {PLANT_PARTS.map((part) => (
        <mesh
          key={part}
          geometry={shape.parts[part]}
          material={materials[part]}
          raycast={() => null}
        />
      ))}
      {/* Dormant seed: a small mound of soil with a faint glow, waiting for evidence. */}
      <mesh ref={seedRef} position={[0, 0.02, 0]} raycast={() => null}>
        <sphereGeometry args={[0.11, 10, 6, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial
          color="#6b5440"
          emissive={groveColor}
          emissiveIntensity={dimmed ? 0.02 : 0.15}
          flatShading
        />
      </mesh>
      <mesh rotation-x={-Math.PI / 2} position={[0, 0.015, 0]} raycast={() => null} renderOrder={2}>
        <planeGeometry args={[1.5, 1.5]} />
        <meshBasicMaterial map={getBlobTexture()} transparent depthWrite={false} opacity={0.6} />
      </mesh>
      {/* Invisible, growth-sized hit targets (the visible mesh is deformed on the GPU). */}
      {interaction === "plant" && (
        <mesh
          position={[0, (stemTop + 0.2) / 2, 0]}
          onClick={(e) => select(e)}
          onPointerOver={hover("plant")}
          onPointerOut={hover(null)}
        >
          <cylinderGeometry args={[0.45, 0.45, stemTop + 0.3, 8]} />
          <meshBasicMaterial visible={false} />
        </mesh>
      )}
      {interaction === "parts" && (
        <>
          <mesh
            position={[0, 0.04, 0]}
            onClick={(e) => select(e, "roots")}
            onPointerOver={hover("roots")}
            onPointerOut={hover(null)}
          >
            <cylinderGeometry args={[0.85, 0.85, 0.12, 12]} />
            <meshBasicMaterial visible={false} />
          </mesh>
          <mesh
            position={[0, stemTop * 0.4, 0]}
            onClick={(e) => select(e, "stem")}
            onPointerOver={hover("stem")}
            onPointerOut={hover(null)}
          >
            <cylinderGeometry args={[0.13, 0.13, stemTop * 0.75, 8]} />
            <meshBasicMaterial visible={false} />
          </mesh>
          {growth.parts.branches.total > 0 && (
            <mesh
              position={[0, stemTop * 0.78, 0]}
              onClick={(e) => select(e, "branches")}
              onPointerOver={hover("branches")}
              onPointerOut={hover(null)}
            >
              <cylinderGeometry args={[0.6, 0.35, stemTop * 0.5, 10]} />
              <meshBasicMaterial visible={false} />
            </mesh>
          )}
          {growth.parts.blossoms.total > 0 && (
            <mesh
              position={[0, stemTop + 0.06, 0]}
              onClick={(e) => select(e, "blossoms")}
              onPointerOver={hover("blossoms")}
              onPointerOut={hover(null)}
            >
              <sphereGeometry args={[0.28, 10, 8]} />
              <meshBasicMaterial visible={false} />
            </mesh>
          )}
        </>
      )}
    </group>
  );
}

export const Plant = memo(PlantImpl);
