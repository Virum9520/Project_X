import * as THREE from "three";

/**
 * Lit, flat-shaded plant material with growth, ghost (assisted) and provisional rendering,
 * wilting and wind injected into MeshStandardMaterial so it keeps scene lighting and fog.
 *
 * - Vertices with `aGrow` above the growth level collapse onto `aSpine` (see plantGeometry).
 * - Growth above `uSolid` (independent) is assisted: screen-door dithered "ghost growth".
 * - Growth above `uConfirmed` is provisional: dithered and glowing (HDR, so it blooms).
 * Screen-door transparency keeps plants in the opaque pass: no sorting artifacts.
 */

export interface PlantUniforms {
  uGrowth: { value: number };
  uSolid: { value: number };
  uConfirmed: { value: number };
  /** Growth of the stem (branches and blossoms ride on it). */
  uParent: { value: number };
  uWilt: { value: number };
  uOpen: { value: number };
  uDim: { value: number };
  uGlow: { value: number };
  uTime: { value: number };
  uHeight: { value: number };
  uSway: { value: number };
  uPhase: { value: number };
  uDroop: { value: THREE.Vector2 };
  uGlowColor: { value: THREE.Color };
  uGhostColor: { value: THREE.Color };
  uWiltColor: { value: THREE.Color };
}

export const GROW_WINDOW = 0.08;

export function createPlantUniforms(height: number, phase: number, droop: number): PlantUniforms {
  return {
    uGrowth: { value: 0 },
    uSolid: { value: 0 },
    uConfirmed: { value: 0 },
    uParent: { value: 1 },
    uWilt: { value: 0 },
    uOpen: { value: 1 },
    uDim: { value: 0 },
    uGlow: { value: 0 },
    uTime: { value: 0 },
    uHeight: { value: height },
    uSway: { value: 0.035 },
    uPhase: { value: phase },
    uDroop: { value: new THREE.Vector2(Math.cos(droop), Math.sin(droop)) },
    uGlowColor: { value: new THREE.Color("#9be7ff").multiplyScalar(1.6) },
    uGhostColor: { value: new THREE.Color("#bfefff") },
    uWiltColor: { value: new THREE.Color("#8a7f6a") },
  };
}

const VERTEX_HEADER = /* glsl */ `
#include <common>
attribute float aGrow;
attribute vec3 aSpine;
attribute vec3 aAttach;
uniform float uGrowth;
uniform float uSolid;
uniform float uConfirmed;
uniform float uParent;
uniform float uWilt;
uniform float uOpen;
uniform float uTime;
uniform float uHeight;
uniform float uSway;
uniform float uPhase;
uniform vec2 uDroop;
varying float vGhost;
varying float vProvisional;
`;

const VERTEX_BODY = /* glsl */ `
vec3 transformed = vec3(position);
// Same reveal curve at each level. A vertex is provisional where it is grown only thanks to
// provisional growth, and ghost where it is grown only thanks to assisted evidence.
float sgK = clamp((uGrowth * (1.0 + ${GROW_WINDOW.toFixed(3)}) - aGrow) / ${GROW_WINDOW.toFixed(3)}, 0.0, 1.0);
float sgKc = clamp((uConfirmed * (1.0 + ${GROW_WINDOW.toFixed(3)}) - aGrow) / ${GROW_WINDOW.toFixed(3)}, 0.0, 1.0);
float sgKs = clamp((uSolid * (1.0 + ${GROW_WINDOW.toFixed(3)}) - aGrow) / ${GROW_WINDOW.toFixed(3)}, 0.0, 1.0);
vProvisional = (sgK - sgKc) / max(sgK, 1e-3);
vGhost = (sgKc - sgKs) / max(sgK, 1e-3);
transformed = mix(aSpine, transformed, sgK * uOpen);
transformed += aAttach * (uParent - 1.0);
float sgH = clamp(transformed.y / uHeight, 0.0, 1.5);
float sgAngle = (uWilt * 1.15 + sin(uTime * 1.3 + uPhase) * uSway) * sgH * sgH;
float sgAlong = dot(transformed.xz, uDroop);
float sgC = cos(sgAngle);
float sgS = sin(sgAngle);
float sgNewAlong = sgAlong * sgC + transformed.y * sgS;
transformed.y = -sgAlong * sgS + transformed.y * sgC;
transformed.xz += uDroop * (sgNewAlong - sgAlong);
`;

const FRAGMENT_HEADER = /* glsl */ `
#include <common>
uniform float uWilt;
uniform float uDim;
uniform float uGlow;
uniform float uTime;
uniform vec3 uGlowColor;
uniform vec3 uGhostColor;
uniform vec3 uWiltColor;
varying float vGhost;
varying float vProvisional;
float sgGhost;
float sgProvisional;
`;

const FRAGMENT_DISCARD = /* glsl */ `
#include <clipping_planes_fragment>
sgGhost = step(0.5, vGhost + vProvisional);
sgProvisional = step(0.5, vProvisional);
float sgNoise = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
if (sgNoise > mix(1.0, mix(0.5, 0.7, sgProvisional), sgGhost)) discard;
`;

const FRAGMENT_COLOR = /* glsl */ `
#include <color_fragment>
vec3 sgBase = diffuseColor.rgb;
float sgLum = dot(sgBase, vec3(0.299, 0.587, 0.114));
sgBase = mix(sgBase, uWiltColor * (0.55 + sgLum), uWilt * 0.7);
sgBase = mix(sgBase, mix(sgBase, uGhostColor, 0.5), sgGhost);
sgBase = mix(sgBase, vec3(sgLum * 0.4), uDim * 0.85);
diffuseColor.rgb = sgBase;
`;

const FRAGMENT_EMISSIVE = /* glsl */ `
#include <emissivemap_fragment>
float sgPulse = 0.5 + 0.5 * sin(uTime * 4.0);
totalEmissiveRadiance += uGhostColor * sgGhost * (1.0 - sgProvisional) * 0.18;
totalEmissiveRadiance += uGlowColor * sgProvisional * (0.6 + 0.8 * sgPulse);
totalEmissiveRadiance += uGlowColor * uGlow * 0.3;
totalEmissiveRadiance *= 1.0 - 0.85 * uDim;
`;

export function createPlantMaterial(
  uniforms: PlantUniforms,
  options: { emissive?: string; emissiveIntensity?: number; roughness?: number } = {},
): THREE.MeshStandardMaterial {
  const material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    flatShading: true,
    side: THREE.DoubleSide,
    roughness: options.roughness ?? 0.75,
    metalness: 0,
    emissive: new THREE.Color(options.emissive ?? "#000000"),
    emissiveIntensity: options.emissiveIntensity ?? 1,
  });
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", VERTEX_HEADER)
      .replace("#include <begin_vertex>", VERTEX_BODY);
    shader.fragmentShader = shader.fragmentShader
      .replace("#include <common>", FRAGMENT_HEADER)
      .replace("#include <clipping_planes_fragment>", FRAGMENT_DISCARD)
      .replace("#include <color_fragment>", FRAGMENT_COLOR)
      .replace("#include <emissivemap_fragment>", FRAGMENT_EMISSIVE);
  };
  material.customProgramCacheKey = () => "sg-plant-v3";
  return material;
}
