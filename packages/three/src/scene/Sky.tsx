"use client";

import { Stars } from "@react-three/drei";
import { useMemo } from "react";
import * as THREE from "three";

import type { Atmosphere } from "./atmosphere";

const SKY_VERTEX = /* glsl */ `
varying vec3 vDir;
void main() {
  vDir = normalize(position);
  vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  gl_Position = p.xyww;
}
`;

const SKY_FRAGMENT = /* glsl */ `
uniform vec3 uTop;
uniform vec3 uHorizon;
uniform vec3 uSunDir;
uniform vec3 uSunColor;
uniform float uDaylight;
varying vec3 vDir;
void main() {
  float y = vDir.y;
  float t = pow(clamp(y * 0.5 + 0.5, 0.0, 1.0), 1.6);
  vec3 color = mix(uHorizon * 0.85, uTop, smoothstep(0.42, 1.0, t));
  // Below the horizon the island floats over a sea of haze.
  color = mix(color, uHorizon * 0.55, smoothstep(0.0, -0.4, y));
  float sun = max(dot(normalize(vDir), normalize(uSunDir)), 0.0);
  color += uSunColor * (pow(sun, 24.0) * 0.35 + pow(sun, 900.0) * 2.5) * (0.35 + 0.65 * uDaylight);
  gl_FragColor = vec4(color, 1.0);
  #include <colorspace_fragment>
}
`;

/** Sky dome, sun/moon light, hemisphere fill, fog and stars for one time of day. */
export function GardenAtmosphere({
  atmosphere,
  islandRadius,
  shadows,
}: {
  atmosphere: Atmosphere;
  islandRadius: number;
  shadows: boolean;
}) {
  const uniforms = useMemo(
    () => ({
      uTop: { value: new THREE.Color() },
      uHorizon: { value: new THREE.Color() },
      uSunDir: { value: new THREE.Vector3() },
      uSunColor: { value: new THREE.Color() },
      uDaylight: { value: 1 },
    }),
    [],
  );
  uniforms.uTop.value.copy(atmosphere.skyTop);
  uniforms.uHorizon.value.copy(atmosphere.skyHorizon);
  uniforms.uSunDir.value.copy(atmosphere.sunDirection);
  uniforms.uSunColor.value.copy(atmosphere.sunColor);
  uniforms.uDaylight.value = atmosphere.daylight;

  const sun = atmosphere.sunDirection.clone().multiplyScalar(islandRadius * 2.2);
  const extent = islandRadius * 1.2;

  return (
    <>
      <color attach="background" args={[atmosphere.fog]} />
      <fog attach="fog" args={[atmosphere.fog, islandRadius * 3.2, islandRadius * 9]} />
      <mesh scale={islandRadius * 12} renderOrder={-1} frustumCulled={false}>
        <sphereGeometry args={[1, 32, 16]} />
        <shaderMaterial
          uniforms={uniforms}
          vertexShader={SKY_VERTEX}
          fragmentShader={SKY_FRAGMENT}
          side={THREE.BackSide}
          depthWrite={false}
          fog={false}
        />
      </mesh>
      {atmosphere.night > 0.3 && (
        <group>
          <Stars
            radius={islandRadius * 7}
            depth={islandRadius * 3}
            count={2500}
            factor={5}
            fade
            speed={0.4}
          />
        </group>
      )}
      {/* Soft fill so stems facing away from the sun still read. */}
      <ambientLight intensity={atmosphere.hemiIntensity * 0.45} color={atmosphere.hemiSky} />
      <hemisphereLight
        args={[atmosphere.hemiSky, atmosphere.hemiGround, atmosphere.hemiIntensity]}
      />
      <directionalLight
        position={sun}
        color={atmosphere.sunColor}
        intensity={atmosphere.sunIntensity}
        castShadow={shadows}
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0004}
        shadow-normalBias={0.03}
        shadow-camera-left={-extent}
        shadow-camera-right={extent}
        shadow-camera-top={extent}
        shadow-camera-bottom={-extent}
        shadow-camera-near={1}
        shadow-camera-far={islandRadius * 6}
      />
    </>
  );
}
