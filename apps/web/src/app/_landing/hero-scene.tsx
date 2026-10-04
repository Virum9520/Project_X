"use client";

import { Edges, Environment, Float, Lightformer, Sparkles, Stars } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

/**
 * Landing hero: a low-poly floating island at night with a blossoming tree, sprouts at different
 * growth stages and iridescent glass shards drifting around it. Self-contained on purpose; the
 * real garden generator lives in `packages/three` (C13).
 */

const COLOR = {
  moss: "#3fae7a",
  mossDeep: "#24704e",
  mossLight: "#6fd39c",
  soil: "#3b2f3a",
  stone: "#2b3456",
  stoneDark: "#1a2140",
  bark: "#5e4636",
  bloom: "#f4b8d4",
  glow: "#9be7ff",
};

/** Deterministic pseudo-random in [0, 1) so the island looks the same on every visit. */
function random(seed: number) {
  const x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

/** Jitter by position (not index) so vertices shared across a UV seam move together. */
function jitter(geometry: THREE.BufferGeometry, amount: number, keepTop = Infinity) {
  const pos = geometry.attributes.position as THREE.BufferAttribute;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i);
    const y = pos.getY(i);
    const z = pos.getZ(i);
    if (y >= keepTop) continue;
    const seed = Math.round(x * 97) * 7.3 + Math.round(y * 89) * 3.1 + Math.round(z * 83) * 1.7;
    pos.setXYZ(
      i,
      x + (random(seed) - 0.5) * amount,
      y + (random(seed + 1) - 0.5) * amount * 0.6,
      z + (random(seed + 2) - 0.5) * amount,
    );
  }
  geometry.computeVertexNormals();
  return geometry;
}

function Island() {
  const rock = useMemo(() => {
    const geometry = new THREE.ConeGeometry(2.05, 2.7, 11, 5);
    geometry.rotateX(Math.PI);
    geometry.translate(0, -1.5, 0);
    return jitter(geometry, 0.28, -0.2);
  }, []);
  const soil = useMemo(() => jitter(new THREE.CylinderGeometry(2.12, 2.05, 0.28, 11, 1), 0.06), []);
  const grass = useMemo(
    () => jitter(new THREE.CylinderGeometry(2.08, 2.14, 0.16, 11, 1), 0.04),
    [],
  );

  return (
    <group>
      <mesh geometry={rock}>
        <meshStandardMaterial color={COLOR.stone} flatShading roughness={0.95} />
      </mesh>
      <mesh geometry={soil} position={[0, -0.08, 0]}>
        <meshStandardMaterial color={COLOR.soil} flatShading roughness={1} />
      </mesh>
      <mesh geometry={grass} position={[0, 0.12, 0]}>
        <meshStandardMaterial color={COLOR.mossDeep} flatShading roughness={0.9} />
      </mesh>
      {[
        [-1.4, -2.4, 0.6, 0.32],
        [1.1, -2.9, -0.4, 0.22],
        [0.3, -3.4, 0.9, 0.16],
      ].map(([x, y, z, r], i) => (
        <Float key={i} speed={1.2} floatIntensity={0.6} rotationIntensity={0.6}>
          <mesh position={[x!, y!, z!]}>
            <dodecahedronGeometry args={[r, 0]} />
            <meshStandardMaterial color={COLOR.stoneDark} flatShading />
          </mesh>
        </Float>
      ))}
    </group>
  );
}

function Tree() {
  const blossoms = useMemo(
    () =>
      Array.from({ length: 22 }, (_, i) => {
        const theta = random(i + 40) * Math.PI * 2;
        const phi = Math.acos(1 - random(i + 80) * 1.3);
        const r = 0.78;
        return new THREE.Vector3(
          r * Math.sin(phi) * Math.cos(theta),
          1.95 + r * Math.cos(phi) * 0.85,
          r * Math.sin(phi) * Math.sin(theta),
        );
      }),
    [],
  );
  return (
    <group position={[-0.25, 0.2, 0.1]}>
      <mesh position={[0, 0.65, 0]}>
        <cylinderGeometry args={[0.08, 0.15, 1.3, 6]} />
        <meshStandardMaterial color={COLOR.bark} flatShading />
      </mesh>
      <mesh position={[0.22, 1.05, 0]} rotation={[0, 0, -0.8]}>
        <cylinderGeometry args={[0.04, 0.06, 0.6, 5]} />
        <meshStandardMaterial color={COLOR.bark} flatShading />
      </mesh>
      {[
        [0, 1.95, 0, 0.78, COLOR.moss],
        [0.5, 1.65, 0.15, 0.5, COLOR.mossDeep],
        [-0.45, 1.7, -0.1, 0.52, COLOR.mossLight],
        [0.05, 2.45, -0.1, 0.45, COLOR.mossLight],
      ].map(([x, y, z, r, color], i) => (
        <mesh key={i} position={[x as number, y as number, z as number]}>
          <icosahedronGeometry args={[r as number, 0]} />
          <meshStandardMaterial color={color as string} flatShading roughness={0.8} />
        </mesh>
      ))}
      {blossoms.map((p, i) => (
        <mesh key={i} position={p}>
          <icosahedronGeometry args={[0.065, 0]} />
          <meshStandardMaterial
            color={COLOR.bloom}
            emissive={COLOR.bloom}
            emissiveIntensity={0.45}
            flatShading
          />
        </mesh>
      ))}
    </group>
  );
}

/** Small plants at increasing stages: seedling, sprout, bush, flowering bush. */
function Sprouts() {
  const plants = [
    { at: [1.3, 0.2, 0.7], stage: 0 },
    { at: [0.95, 0.2, -0.95], stage: 1 },
    { at: [-1.35, 0.2, 0.75], stage: 2 },
    { at: [1.55, 0.2, -0.15], stage: 3 },
    { at: [-0.9, 0.2, -1.2], stage: 1 },
    { at: [0.35, 0.2, 1.45], stage: 2 },
  ] as const;
  return (
    <>
      {plants.map(({ at, stage }, i) => (
        <group key={i} position={[at[0], at[1], at[2]]} rotation={[0, random(i) * 6, 0]}>
          <mesh position={[0, 0.12 + stage * 0.04, 0]}>
            <cylinderGeometry args={[0.015, 0.025, 0.24 + stage * 0.08, 4]} />
            <meshStandardMaterial color={COLOR.mossDeep} />
          </mesh>
          {stage < 2 ? (
            [-1, 1].map((side) => (
              <mesh
                key={side}
                position={[side * 0.07, 0.24 + stage * 0.08, 0]}
                rotation={[0, 0, side * -0.9]}
                scale={[1, 0.35, 0.6]}
              >
                <sphereGeometry args={[0.08 + stage * 0.03, 6, 4]} />
                <meshStandardMaterial color={COLOR.mossLight} flatShading />
              </mesh>
            ))
          ) : (
            <mesh position={[0, 0.34 + stage * 0.06, 0]}>
              <icosahedronGeometry args={[0.2 + stage * 0.03, 0]} />
              <meshStandardMaterial color={COLOR.moss} flatShading />
            </mesh>
          )}
          {stage === 3 &&
            [0, 1, 2, 3].map((k) => (
              <mesh
                key={k}
                position={[Math.cos(k * 1.7) * 0.2, 0.55 + (k % 2) * 0.08, Math.sin(k * 1.7) * 0.2]}
              >
                <icosahedronGeometry args={[0.045, 0]} />
                <meshStandardMaterial
                  color={COLOR.bloom}
                  emissive={COLOR.bloom}
                  emissiveIntensity={0.6}
                />
              </mesh>
            ))}
        </group>
      ))}
    </>
  );
}

const SHARD_TINTS = ["#bfefff", "#f7cde1", "#d9fbe8"];

function Crystals({ calm }: { calm: boolean }) {
  const shards = [
    { at: [-2.9, 1.5, -0.6], s: 0.9, r: 0.4 },
    { at: [2.8, 1.9, -0.9], s: 1.1, r: -0.3 },
    { at: [3.2, -0.6, 0.4], s: 0.7, r: 0.8 },
    { at: [-2.4, -1.1, 1.0], s: 0.6, r: -0.6 },
    { at: [0.9, 3.1, -1.6], s: 0.55, r: 0.2 },
    { at: [-1.2, -2.2, -1.8], s: 0.8, r: 1.1 },
  ] as const;
  return (
    <>
      {shards.map(({ at, s, r }, i) => (
        <Float
          key={i}
          speed={calm ? 0 : 1 + random(i + 7)}
          rotationIntensity={calm ? 0 : 1.2}
          floatIntensity={calm ? 0 : 1.4}
        >
          <mesh
            position={[at[0], at[1], at[2]]}
            rotation={[r, r * 2, r * 0.5]}
            scale={[s * 0.45, s, s * 0.45]}
          >
            <octahedronGeometry args={[0.7, 0]} />
            <meshPhysicalMaterial
              color={SHARD_TINTS[i % SHARD_TINTS.length]}
              emissive={SHARD_TINTS[i % SHARD_TINTS.length]}
              emissiveIntensity={0.18}
              transparent
              opacity={0.62}
              roughness={0.05}
              metalness={0.15}
              iridescence={1}
              iridescenceIOR={1.4}
              iridescenceThicknessRange={[200, 1000]}
              clearcoat={1}
              envMapIntensity={2.6}
              depthWrite={false}
              flatShading
            />
            <Edges threshold={15} color="#ffffff" transparent opacity={0.55} />
          </mesh>
        </Float>
      ))}
    </>
  );
}

/** Keep the whole island in frame on narrow screens by backing the camera off. */
function CameraRig() {
  const fittedAspect = useRef(0);
  useFrame(({ camera, size }) => {
    const aspect = size.width / size.height;
    if (aspect === fittedAspect.current || !(camera instanceof THREE.PerspectiveCamera)) return;
    fittedAspect.current = aspect;
    const halfFov = THREE.MathUtils.degToRad(camera.fov / 2);
    camera.position.z = Math.max(10, 7.6 / (2 * Math.tan(halfFov) * aspect));
    camera.updateProjectionMatrix();
  });
  return null;
}

function Garden({ calm }: { calm: boolean }) {
  const group = useRef<THREE.Group>(null);
  // On desktop the canvas sits beside the copy; nudge the island away from it.
  const wide = useThree((state) => state.size.width > 700);
  useFrame((state, delta) => {
    const g = group.current;
    if (!g) return;
    if (!calm) g.rotation.y += delta * 0.07;
    // Lean gently toward the pointer.
    g.rotation.x = THREE.MathUtils.damp(g.rotation.x, state.pointer.y * -0.08, 3, delta);
    g.rotation.z = THREE.MathUtils.damp(g.rotation.z, state.pointer.x * -0.05, 3, delta);
  });
  return (
    <group ref={group} position={[wide ? 1.15 : 0, -0.95, 0]} scale={wide ? 1.22 : 1.05}>
      <Float speed={calm ? 0 : 0.8} floatIntensity={0.5} rotationIntensity={0.05}>
        <Island />
        <Tree />
        <Sprouts />
        <pointLight
          position={[-0.2, 1.4, 0.6]}
          color={COLOR.mossLight}
          intensity={5}
          distance={4}
        />
      </Float>
      <Crystals calm={calm} />
      <Sparkles
        count={70}
        scale={[7, 5, 7]}
        position={[0, 1, 0]}
        size={3.2}
        speed={calm ? 0 : 0.35}
        color={COLOR.glow}
        opacity={0.9}
      />
    </group>
  );
}

export default function HeroScene() {
  const container = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(true);
  const [ready, setReady] = useState(false);
  const [calm] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  // Stop rendering while the hero is scrolled away.
  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const observer = new IntersectionObserver(([entry]) =>
      setVisible(Boolean(entry?.isIntersecting)),
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={container}
      className={`size-full transition-opacity duration-[1500ms] ${ready ? "opacity-100" : "opacity-0"}`}
    >
      <Canvas
        camera={{ position: [0, 1.1, 10.5], fov: 38 }}
        dpr={[1, 1.75]}
        gl={{ antialias: true, alpha: true }}
        frameloop={visible ? "always" : "never"}
        onCreated={() => setReady(true)}
      >
        <ambientLight intensity={0.35} />
        <hemisphereLight args={[COLOR.glow, "#0b1020", 0.7]} />
        <directionalLight position={[4, 6, 4]} intensity={1.8} color="#d6ecff" />
        <pointLight position={[-4, -1, 3]} color={COLOR.bloom} intensity={18} distance={12} />
        {/* Cool rim light so the rock underside reads against the night sky. */}
        <pointLight position={[1.5, -4, -2.5]} color={COLOR.glow} intensity={22} distance={10} />
        <Environment resolution={256}>
          <Lightformer
            form="rect"
            intensity={2.5}
            color={COLOR.glow}
            position={[0, 5, -6]}
            scale={[12, 3, 1]}
          />
          <Lightformer
            form="ring"
            intensity={4}
            color={COLOR.bloom}
            position={[-6, 1, 2]}
            scale={3}
          />
          <Lightformer
            form="rect"
            intensity={3}
            color={COLOR.mossLight}
            position={[6, 0, 3]}
            scale={[3, 6, 1]}
          />
          <Lightformer form="circle" intensity={2} color="#ffffff" position={[2, 4, 6]} scale={2} />
        </Environment>
        <Stars
          radius={60}
          depth={30}
          count={1400}
          factor={3}
          saturation={0}
          fade
          speed={calm ? 0 : 0.6}
        />
        <CameraRig />
        <Garden calm={calm} />
      </Canvas>
    </div>
  );
}
