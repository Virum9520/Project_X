"use client";

import { Float } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import type { GardenLayout } from "../generator/layout";
import { createRng, hashString, range } from "../generator/random";
import { valueNoise } from "../generator/terrain";

/** The floating island: terrain top, rocky underside, pond, instanced grass and rocks. */

const RINGS = 56;
const SEGMENTS = 144;

const COLORS = {
  grass: new THREE.Color("#3fae7a"),
  grassDeep: new THREE.Color("#24704e"),
  grassLight: new THREE.Color("#6fd39c"),
  sand: new THREE.Color("#d8c79c"),
  soil: new THREE.Color("#5e4636"),
  stone: new THREE.Color("#3a4470"),
  stoneDark: new THREE.Color("#1a2140"),
};

function buildTop(layout: GardenLayout): THREE.BufferGeometry {
  const { islandRadius: R, pondRadius, terrain } = layout;
  const seed = hashString(`${layout.seed}:grass`);
  const positions: number[] = [];
  const colors: number[] = [];
  const indices: number[] = [];
  const color = new THREE.Color();
  const push = (x: number, z: number) => {
    const y = terrain(x, z);
    positions.push(x, y, z);
    const r = Math.hypot(x, z);
    const patch = valueNoise(seed, x * 0.35, z * 0.35);
    color
      .copy(COLORS.grassDeep)
      .lerp(COLORS.grass, patch)
      .lerp(COLORS.grassLight, Math.max(0, patch - 0.65));
    const shore = 1 - THREE.MathUtils.smoothstep(r, pondRadius * 1.05, pondRadius * 1.4);
    color.lerp(COLORS.sand, shore);
    const rim = THREE.MathUtils.smoothstep(r / R, 0.95, 1);
    color.lerp(COLORS.soil, rim * 0.7);
    colors.push(color.r, color.g, color.b);
  };
  push(0, 0);
  for (let i = 1; i <= RINGS; i++) {
    const r = (i / RINGS) * R;
    for (let j = 0; j < SEGMENTS; j++) {
      const a = (j / SEGMENTS) * Math.PI * 2;
      push(Math.cos(a) * r, Math.sin(a) * r);
    }
  }
  for (let j = 0; j < SEGMENTS; j++) indices.push(0, 1 + ((j + 1) % SEGMENTS), 1 + j);
  for (let i = 1; i < RINGS; i++) {
    const inner = 1 + (i - 1) * SEGMENTS;
    const outer = 1 + i * SEGMENTS;
    for (let j = 0; j < SEGMENTS; j++) {
      const j1 = (j + 1) % SEGMENTS;
      indices.push(inner + j, inner + j1, outer + j, inner + j1, outer + j1, outer + j);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  g.setIndex(indices);
  g.computeVertexNormals();
  return g;
}

function buildUnderside(layout: GardenLayout): THREE.BufferGeometry {
  const { islandRadius: R, terrain } = layout;
  const seed = hashString(`${layout.seed}:rock`);
  const layers = 16;
  const depth = R * 0.9;
  const positions: number[] = [];
  const colors: number[] = [];
  const indices: number[] = [];
  const color = new THREE.Color();
  for (let i = 0; i <= layers; i++) {
    const v = i / layers;
    for (let j = 0; j < SEGMENTS; j++) {
      const a = (j / SEGMENTS) * Math.PI * 2;
      const rimX = Math.cos(a) * R;
      const rimZ = Math.sin(a) * R;
      const rimY = terrain(rimX, rimZ);
      const jag =
        i === 0 ? 0 : (valueNoise(seed, a * 9, v * 6) - 0.5) * R * 0.16 * Math.sin(v * Math.PI);
      const r = Math.max(0, R * (1 - 0.94 * Math.pow(v, 1.15)) + jag);
      const y =
        rimY -
        depth * Math.pow(v, 0.9) +
        (i === 0 ? 0 : (valueNoise(seed + 9, a * 5, v * 4) - 0.5) * 0.6);
      positions.push(Math.cos(a) * r, y, Math.sin(a) * r);
      const band = valueNoise(seed + 3, a * 3, v * 12);
      if (v < 0.07) color.copy(COLORS.soil);
      else
        color.copy(COLORS.stone).lerp(COLORS.stoneDark, Math.min(1, v * 1.2 + band * 0.3 - 0.15));
      colors.push(color.r, color.g, color.b);
    }
  }
  const tip = positions.length / 3;
  positions.push(0, terrain(R, 0) - depth * 1.12, 0);
  colors.push(COLORS.stoneDark.r, COLORS.stoneDark.g, COLORS.stoneDark.b);
  for (let i = 0; i < layers; i++) {
    for (let j = 0; j < SEGMENTS; j++) {
      const j1 = (j + 1) % SEGMENTS;
      const a = i * SEGMENTS + j;
      const b = i * SEGMENTS + j1;
      indices.push(a, b, a + SEGMENTS, b, b + SEGMENTS, a + SEGMENTS);
    }
  }
  for (let j = 0; j < SEGMENTS; j++) {
    indices.push(layers * SEGMENTS + j, layers * SEGMENTS + ((j + 1) % SEGMENTS), tip);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  g.setIndex(indices);
  g.computeVertexNormals();
  return g;
}

const WATER_VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const WATER_FRAGMENT = /* glsl */ `
uniform float uTime;
uniform float uNight;
uniform vec3 uDeep;
uniform vec3 uShallow;
uniform vec3 uGlow;
varying vec2 vUv;
void main() {
  vec2 p = vUv - 0.5;
  float r = length(p) * 2.0;
  vec3 color = mix(uDeep, uShallow, smoothstep(0.1, 1.0, r));
  float ripple = smoothstep(0.92, 1.0, sin(r * 34.0 - uTime * 1.4 + sin(atan(p.y, p.x) * 3.0) * 0.6));
  color += ripple * 0.08;
  float sparkle = step(0.995, fract(sin(dot(floor(vUv * 160.0), vec2(12.9898, 78.233)) + floor(uTime * 2.0)) * 43758.5453));
  color += sparkle * 0.5 * (1.0 - uNight * 0.5);
  // The pond glows softly at night, like a mirror of the sky.
  color += uGlow * uNight * (0.25 + 0.25 * (1.0 - r));
  gl_FragColor = vec4(color, 0.9);
  #include <colorspace_fragment>
}
`;

function Water({ layout, night }: { layout: GardenLayout; night: number }) {
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uNight: { value: night },
      uDeep: { value: new THREE.Color("#1f5f7a") },
      uShallow: { value: new THREE.Color("#5fc2c9") },
      uGlow: { value: new THREE.Color("#9be7ff") },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  uniforms.uNight.value = night;
  useFrame((state) => {
    uniforms.uTime.value = state.clock.elapsedTime;
  });
  return (
    <mesh rotation-x={-Math.PI / 2} position={[0, layout.waterLevel, 0]} renderOrder={1}>
      <circleGeometry args={[layout.pondRadius * 1.25, 64]} />
      <shaderMaterial
        uniforms={uniforms}
        vertexShader={WATER_VERTEX}
        fragmentShader={WATER_FRAGMENT}
        transparent
        depthWrite={false}
      />
    </mesh>
  );
}

function LilyPads({ layout }: { layout: GardenLayout }) {
  const pads = useMemo(() => {
    const rng = createRng(`${layout.seed}:lily`);
    return Array.from({ length: 6 }, (_, i) => {
      const a = (i / 6) * Math.PI * 2 + range(rng, -0.4, 0.4);
      const r = range(rng, 0.5, layout.pondRadius * 0.75);
      return {
        x: Math.cos(a) * r,
        z: Math.sin(a) * r,
        s: range(rng, 0.18, 0.3),
        flower: i % 3 === 0,
      };
    });
  }, [layout]);
  return (
    <group position={[0, layout.waterLevel + 0.01, 0]}>
      {pads.map((pad, i) => (
        <group key={i} position={[pad.x, 0, pad.z]}>
          <mesh scale={[pad.s, 0.02, pad.s]}>
            <cylinderGeometry args={[1, 1, 1, 10, 1, false, 0.3, Math.PI * 2 - 0.6]} />
            <meshStandardMaterial color="#3f9a5e" flatShading roughness={0.6} />
          </mesh>
          {pad.flower && (
            <mesh position={[0, 0.06, 0]} scale={0.08}>
              <octahedronGeometry args={[1, 0]} />
              <meshStandardMaterial
                color="#f4b8d4"
                emissive="#f4b8d4"
                emissiveIntensity={1.4}
                toneMapped={false}
                flatShading
              />
            </mesh>
          )}
        </group>
      ))}
    </group>
  );
}

const GRASS_HEADER = /* glsl */ `
#include <common>
uniform float uTime;
`;
const GRASS_BODY = /* glsl */ `
vec3 transformed = vec3(position);
vec4 sgRoot = instanceMatrix * vec4(0.0, 0.0, 0.0, 1.0);
float sgBend = position.y * position.y;
transformed.x += sin(uTime * 1.6 + sgRoot.x * 0.7 + sgRoot.z * 0.45) * 0.35 * sgBend;
transformed.z += cos(uTime * 1.2 + sgRoot.z * 0.6) * 0.18 * sgBend;
`;

function bladeGeometry(): THREE.BufferGeometry {
  const w = 0.035;
  const h = 0.22;
  const positions = [-w, 0, 0, w, 0, 0, -w * 0.6, h * 0.5, 0, w * 0.6, h * 0.5, 0, 0, h, 0];
  const base = new THREE.Color("#3a9466");
  const tip = new THREE.Color("#b5f0c4");
  const colors = [
    base,
    base,
    base.clone().lerp(tip, 0.5),
    base.clone().lerp(tip, 0.5),
    tip,
  ].flatMap((c) => [c.r, c.g, c.b]);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  g.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  g.setIndex([0, 1, 2, 1, 3, 2, 2, 3, 4]);
  g.computeVertexNormals();
  return g;
}

function Grass({ layout, count }: { layout: GardenLayout; count: number }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const geometry = useMemo(bladeGeometry, []);
  const uniforms = useMemo(() => ({ uTime: { value: 0 } }), []);
  const material = useMemo(() => {
    const m = new THREE.MeshStandardMaterial({
      vertexColors: true,
      side: THREE.DoubleSide,
      roughness: 0.9,
    });
    m.onBeforeCompile = (shader) => {
      Object.assign(shader.uniforms, uniforms);
      shader.vertexShader = shader.vertexShader
        .replace("#include <common>", GRASS_HEADER)
        .replace("#include <begin_vertex>", GRASS_BODY);
    };
    m.customProgramCacheKey = () => "sg-grass-v1";
    return m;
  }, [uniforms]);

  useEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const { islandRadius: R, pondRadius, terrain } = layout;
    const plants = [...layout.plants.values()].map((p) => p.position);
    const rng = createRng(`${layout.seed}:blades`);
    const patchSeed = hashString(`${layout.seed}:meadow`);
    const matrix = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const s = new THREE.Vector3();
    const p = new THREE.Vector3();
    const tint = new THREE.Color();
    let placed = 0;
    for (let attempt = 0; placed < count && attempt < count * 8; attempt++) {
      const r = R * 0.95 * Math.sqrt(rng());
      const a = rng() * Math.PI * 2;
      const x = Math.cos(a) * r;
      const z = Math.sin(a) * r;
      if (r < pondRadius * 1.3) continue;
      // Meadow patches rather than an even fuzz.
      if (valueNoise(patchSeed, x * 0.45, z * 0.45) < 0.42 + rng() * 0.2) continue;
      if (plants.some(([px, , pz]) => (px - x) ** 2 + (pz - z) ** 2 < 0.3)) continue;
      p.set(x, terrain(x, z) - 0.02, z);
      q.setFromAxisAngle(THREE.Object3D.DEFAULT_UP, rng() * Math.PI * 2);
      const k = range(rng, 0.6, 1.35);
      s.set(k, k * range(rng, 0.8, 1.3), k);
      matrix.compose(p, q, s);
      mesh.setMatrixAt(placed, matrix);
      tint.setHSL(range(rng, 0.3, 0.4), range(rng, 0.2, 0.45), range(rng, 0.72, 0.9));
      mesh.setColorAt(placed, tint);
      placed++;
    }
    mesh.count = placed;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [layout, count]);

  useFrame((state) => {
    uniforms.uTime.value = state.clock.elapsedTime;
  });

  return (
    <instancedMesh
      ref={ref}
      args={[geometry, material, count]}
      receiveShadow
      raycast={() => null}
      frustumCulled={false}
    />
  );
}

function Rocks({ layout }: { layout: GardenLayout }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const count = 46;
  useEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const { islandRadius: R, pondRadius, terrain } = layout;
    const rng = createRng(`${layout.seed}:rocks`);
    const m = new THREE.Matrix4();
    const e = new THREE.Euler();
    const q = new THREE.Quaternion();
    for (let i = 0; i < count; i++) {
      const aroundPond = i < 14;
      const a = aroundPond ? (i / 14) * Math.PI * 2 + range(rng, -0.1, 0.1) : rng() * Math.PI * 2;
      const r = aroundPond ? pondRadius * range(rng, 1.12, 1.25) : R * range(rng, 0.86, 0.98);
      const x = Math.cos(a) * r;
      const z = Math.sin(a) * r;
      const k = aroundPond ? range(rng, 0.12, 0.22) : range(rng, 0.15, 0.5);
      e.set(rng() * 3, rng() * 3, rng() * 3);
      m.compose(
        new THREE.Vector3(x, terrain(x, z) + k * 0.2, z),
        q.setFromEuler(e),
        new THREE.Vector3(k, k * range(rng, 0.5, 0.8), k * range(rng, 0.8, 1.2)),
      );
      mesh.setMatrixAt(i, m);
    }
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [layout]);
  return (
    <instancedMesh
      ref={ref}
      args={[undefined, undefined, count]}
      castShadow
      receiveShadow
      raycast={() => null}
    >
      <dodecahedronGeometry args={[1, 0]} />
      <meshStandardMaterial color="#6b7396" flatShading roughness={0.95} />
    </instancedMesh>
  );
}

/** Glowing crystals in the island's underside and small floating islets: the mythic touch. */
function MythicDetails({ layout }: { layout: GardenLayout }) {
  const { islandRadius: R, terrain } = layout;
  const crystals = useMemo(() => {
    const rng = createRng(`${layout.seed}:crystals`);
    return Array.from({ length: 9 }, () => {
      const a = rng() * Math.PI * 2;
      const v = range(rng, 0.25, 0.6);
      const r = R * (1 - 0.94 * Math.pow(v, 1.15)) * 0.98;
      return {
        position: [
          Math.cos(a) * r,
          terrain(R, 0) - R * 0.9 * Math.pow(v, 0.9),
          Math.sin(a) * r,
        ] as const,
        rotation: [range(rng, -0.6, 0.6), a, range(rng, 2.4, 3.6)] as const,
        scale: range(rng, 0.25, 0.6),
      };
    });
  }, [layout, R, terrain]);
  const islets = useMemo(() => {
    const rng = createRng(`${layout.seed}:islets`);
    return Array.from({ length: 6 }, (_, i) => {
      const a = (i / 6) * Math.PI * 2 + range(rng, -0.3, 0.3);
      const r = R * range(rng, 1.3, 1.7);
      return {
        x: Math.cos(a) * r,
        y: range(rng, -3, 2.5),
        z: Math.sin(a) * r,
        s: range(rng, 0.5, 1.2),
      };
    });
  }, [layout, R]);
  return (
    <>
      {crystals.map((c, i) => (
        <mesh
          key={i}
          position={c.position}
          rotation={c.rotation}
          scale={[c.scale * 0.45, c.scale, c.scale * 0.45]}
          raycast={() => null}
        >
          <octahedronGeometry args={[1, 0]} />
          <meshStandardMaterial
            color="#9be7ff"
            emissive="#9be7ff"
            emissiveIntensity={1.6}
            toneMapped={false}
            flatShading
          />
        </mesh>
      ))}
      {islets.map((islet, i) => (
        <Float key={i} speed={0.6 + i * 0.1} floatIntensity={0.8} rotationIntensity={0.15}>
          <group position={[islet.x, islet.y, islet.z]} scale={islet.s}>
            <mesh position={[0, -0.55, 0]} rotation-x={Math.PI} raycast={() => null}>
              <coneGeometry args={[0.9, 1.6, 7]} />
              <meshStandardMaterial color="#2b3456" flatShading roughness={1} />
            </mesh>
            <mesh position={[0, 0.27, 0]} raycast={() => null}>
              <cylinderGeometry args={[0.92, 0.9, 0.14, 7]} />
              <meshStandardMaterial color="#3fae7a" flatShading roughness={0.9} />
            </mesh>
          </group>
        </Float>
      ))}
    </>
  );
}

export function Island({
  layout,
  night,
  grassCount,
}: {
  layout: GardenLayout;
  night: number;
  grassCount: number;
}) {
  const top = useMemo(() => buildTop(layout), [layout]);
  const underside = useMemo(() => buildUnderside(layout), [layout]);
  useEffect(
    () => () => {
      top.dispose();
      underside.dispose();
    },
    [top, underside],
  );
  return (
    <group>
      <mesh geometry={top} receiveShadow raycast={() => null}>
        <meshStandardMaterial vertexColors flatShading roughness={0.95} />
      </mesh>
      <mesh geometry={underside} castShadow raycast={() => null}>
        <meshStandardMaterial vertexColors flatShading roughness={1} />
      </mesh>
      <Water layout={layout} night={night} />
      <LilyPads layout={layout} />
      <Grass layout={layout} count={grassCount} />
      <Rocks layout={layout} />
      <MythicDetails layout={layout} />
    </group>
  );
}
