"use client";

import type { PlantSnapshot } from "@sg/contracts";
import { useCursor } from "@react-three/drei";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";

import type { GardenLayout, GroveLayout } from "../generator/layout";
import { plantVigor } from "../model/growth";
import { ElderTree } from "./ElderTree";

/** Grove ground disc draped over the terrain; `aRadial` runs 0 at the center to 1 at the rim. */
function drapedDisc(layout: GardenLayout, grove: GroveLayout, inner: number, outer: number) {
  const segments = 72;
  const rings = 6;
  const [cx, , cz] = grove.center;
  const positions: number[] = [];
  const radial: number[] = [];
  const indices: number[] = [];
  for (let i = 0; i <= rings; i++) {
    const r = inner + ((outer - inner) * i) / rings;
    for (let j = 0; j < segments; j++) {
      const a = (j / segments) * Math.PI * 2;
      const x = cx + Math.cos(a) * r;
      const z = cz + Math.sin(a) * r;
      positions.push(x, layout.terrain(x, z) + 0.03, z);
      radial.push(i / rings);
    }
  }
  for (let i = 0; i < rings; i++) {
    for (let j = 0; j < segments; j++) {
      const a = i * segments + j;
      const b = i * segments + ((j + 1) % segments);
      indices.push(a, a + segments, b, b, a + segments, b + segments);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  g.setAttribute("aRadial", new THREE.Float32BufferAttribute(radial, 1));
  g.setIndex(indices);
  g.computeBoundingSphere();
  return g;
}

const AURA_VERTEX = /* glsl */ `
attribute float aRadial;
varying float vRadial;
void main() {
  vRadial = aRadial;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const AURA_FRAGMENT = /* glsl */ `
uniform vec3 uColor;
uniform float uIntensity;
uniform float uTime;
varying float vRadial;
void main() {
  float band = smoothstep(0.0, 0.55, vRadial) * smoothstep(1.0, 0.6, vRadial);
  float shimmer = 0.85 + 0.15 * sin(uTime * 1.5 + vRadial * 12.0);
  gl_FragColor = vec4(uColor * uIntensity * shimmer, band);
}
`;

export interface GroveStats {
  health: number;
  plants: number;
  grown: number;
  due: number;
}

export function groveStats(plants: PlantSnapshot[]): GroveStats {
  const health = plants.length ? plants.reduce((s, p) => s + plantVigor(p), 0) / plants.length : 0;
  return {
    health,
    plants: plants.length,
    grown: plants.filter((p) => p.status !== "unassessed").length,
    due: plants.filter((p) => p.status === "due" || p.status === "wilting").length,
  };
}

interface GroveProps {
  layout: GardenLayout;
  grove: GroveLayout;
  stats: GroveStats;
  focused: boolean;
  dimmed: boolean;
  interactive: boolean;
  elderTrees: boolean;
  onSelect: (groveId: string) => void;
}

export function Grove({
  layout,
  grove,
  stats,
  focused,
  dimmed,
  interactive,
  elderTrees,
  onSelect,
}: GroveProps) {
  const aura = useMemo(
    () => drapedDisc(layout, grove, grove.radius - 0.35, grove.radius + 0.35),
    [layout, grove],
  );
  const disc = useMemo(() => drapedDisc(layout, grove, 0, grove.radius), [layout, grove]);
  useEffect(
    () => () => {
      aura.dispose();
      disc.dispose();
    },
    [aura, disc],
  );
  const uniforms = useMemo(
    () => ({
      uColor: { value: new THREE.Color(grove.color) },
      uIntensity: { value: 0 },
      uTime: { value: 0 },
    }),
    [grove.color],
  );
  const [hovered, setHovered] = useState(false);
  useCursor(hovered && interactive);

  useFrame((state, delta) => {
    uniforms.uTime.value = state.clock.elapsedTime;
    // The health aura brightens with grove growth, and glows past 1 (bloom) when focused.
    const target =
      (0.25 + 0.75 * stats.health) *
      (focused ? 2.2 : hovered && interactive ? 1.6 : 1) *
      (dimmed ? 0.3 : 1);
    uniforms.uIntensity.value = THREE.MathUtils.damp(
      uniforms.uIntensity.value,
      target,
      4,
      Math.min(delta, 0.1),
    );
  });

  return (
    <group>
      <mesh geometry={aura} raycast={() => null} renderOrder={3}>
        <shaderMaterial
          uniforms={uniforms}
          vertexShader={AURA_VERTEX}
          fragmentShader={AURA_FRAGMENT}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          toneMapped={false}
        />
      </mesh>
      {interactive && (
        <mesh
          geometry={disc}
          onClick={(e: ThreeEvent<MouseEvent>) => {
            e.stopPropagation();
            onSelect(grove.id);
          }}
          onPointerOver={(e) => {
            e.stopPropagation();
            setHovered(true);
          }}
          onPointerOut={() => setHovered(false)}
        >
          <meshBasicMaterial visible={false} />
        </mesh>
      )}
      {elderTrees && <ElderTree grove={grove} health={stats.health} />}
    </group>
  );
}
