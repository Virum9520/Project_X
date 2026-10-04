"use client";

import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import * as THREE from "three";

import type { GardenLayout } from "../generator/layout";
import { createRng, range } from "../generator/random";

const VERTEX = /* glsl */ `
attribute float aPhase;
uniform float uTime;
uniform float uPixelRatio;
varying float vBlink;
void main() {
  vec3 p = position;
  p.x += sin(uTime * 0.5 + aPhase * 6.0) * 0.35;
  p.y += sin(uTime * 0.8 + aPhase * 11.0) * 0.25;
  p.z += cos(uTime * 0.45 + aPhase * 7.0) * 0.35;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = 70.0 * uPixelRatio / -mv.z;
  vBlink = 0.4 + 0.6 * pow(0.5 + 0.5 * sin(uTime * 2.0 + aPhase * 20.0), 3.0);
}
`;

const FRAGMENT = /* glsl */ `
uniform vec3 uColor;
uniform float uIntensity;
varying float vBlink;
void main() {
  float d = length(gl_PointCoord - 0.5);
  float a = smoothstep(0.5, 0.0, d);
  a *= a;
  gl_FragColor = vec4(uColor * 2.5 * vBlink * uIntensity, a * vBlink * uIntensity);
}
`;

/** Fireflies drifting over the groves; brightest at night. */
export function Fireflies({
  layout,
  count,
  night,
}: {
  layout: GardenLayout;
  count: number;
  night: number;
}) {
  const geometry = useMemo(() => {
    const rng = createRng(`${layout.seed}:fireflies`);
    const positions = new Float32Array(count * 3);
    const phases = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      const grove = layout.groves[i % Math.max(1, layout.groves.length)];
      const [cx, , cz] = grove?.center ?? [0, 0, 0];
      const r = (grove?.radius ?? layout.islandRadius) * 1.3 * Math.sqrt(rng());
      const a = rng() * Math.PI * 2;
      const x = cx + Math.cos(a) * r;
      const z = cz + Math.sin(a) * r;
      positions.set([x, layout.terrain(x, z) + range(rng, 0.4, 2.4), z], i * 3);
      phases[i] = rng();
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    g.setAttribute("aPhase", new THREE.BufferAttribute(phases, 1));
    return g;
  }, [layout, count]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uPixelRatio: { value: 1 },
      uColor: { value: new THREE.Color("#ffe9a8") },
      uIntensity: { value: 0 },
    }),
    [],
  );
  useFrame((state) => {
    uniforms.uTime.value = state.clock.elapsedTime;
    uniforms.uPixelRatio.value = state.viewport.dpr;
    uniforms.uIntensity.value = 0.2 + 0.8 * night;
  });
  return (
    <points geometry={geometry} raycast={() => null} frustumCulled={false}>
      <shaderMaterial
        uniforms={uniforms}
        vertexShader={VERTEX}
        fragmentShader={FRAGMENT}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        toneMapped={false}
      />
    </points>
  );
}
