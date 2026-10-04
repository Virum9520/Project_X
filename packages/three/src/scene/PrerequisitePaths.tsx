"use client";

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import * as THREE from "three";

import type { GardenLayout, PathLayout } from "../generator/layout";

const PATH_VERTEX = /* glsl */ `
varying float vT;
void main() {
  vT = uv.x;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

// Light flows from the prerequisite toward the concept that builds on it.
const PATH_FRAGMENT = /* glsl */ `
uniform vec3 uColor;
uniform float uIntensity;
uniform float uTime;
uniform float uSeed;
varying float vT;
void main() {
  float flow = smoothstep(0.82, 1.0, fract(vT * 2.0 - uTime * 0.35 + uSeed));
  float ends = smoothstep(0.0, 0.08, vT) * smoothstep(1.0, 0.92, vT);
  float a = (0.35 + 1.4 * flow) * ends * uIntensity;
  gl_FragColor = vec4(uColor * a, a);
}
`;

export interface PathState {
  /** 0 hidden … 1 normal … >1 highlighted (blooms). */
  intensity: number;
}

function PrerequisitePath({
  path,
  color,
  intensity,
  seed,
}: {
  path: PathLayout;
  color: string;
  intensity: number;
  seed: number;
}) {
  const geometry = useMemo(() => {
    const curve = new THREE.CatmullRomCurve3(
      path.points.map(([x, y, z]) => new THREE.Vector3(x, y, z)),
    );
    return new THREE.TubeGeometry(
      curve,
      Math.max(16, path.points.length * 2),
      path.crossGrove ? 0.05 : 0.038,
      5,
      false,
    );
  }, [path]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  const uniforms = useMemo(
    () => ({
      uColor: { value: new THREE.Color(color) },
      uIntensity: { value: 0 },
      uTime: { value: 0 },
      uSeed: { value: seed },
    }),
    [color, seed],
  );
  useFrame((state, delta) => {
    uniforms.uTime.value = state.clock.elapsedTime;
    uniforms.uIntensity.value = THREE.MathUtils.damp(
      uniforms.uIntensity.value,
      intensity,
      3,
      Math.min(delta, 0.1),
    );
  });
  return (
    <mesh geometry={geometry} raycast={() => null} renderOrder={4}>
      <shaderMaterial
        uniforms={uniforms}
        vertexShader={PATH_VERTEX}
        fragmentShader={PATH_FRAGMENT}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        toneMapped={false}
      />
    </mesh>
  );
}

/** Glowing prerequisite root paths between concept plants. */
export function PrerequisitePaths({
  layout,
  intensityFor,
}: {
  layout: GardenLayout;
  intensityFor: (path: PathLayout) => number;
}) {
  return (
    <group>
      {layout.paths.map((path, i) => {
        const from = layout.plants.get(path.from);
        const grove = from ? layout.groveById.get(from.groveId) : undefined;
        return (
          <PrerequisitePath
            key={`${path.from}>${path.to}`}
            path={path}
            color={path.crossGrove ? "#9be7ff" : (grove?.color ?? "#9be7ff")}
            intensity={intensityFor(path)}
            seed={(i * 0.37) % 1}
          />
        );
      })}
    </group>
  );
}
