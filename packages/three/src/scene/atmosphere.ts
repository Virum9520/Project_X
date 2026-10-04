import * as THREE from "three";

/** Day-night palette for the garden, keyed by the learner's local hour (0–24). */

export interface Atmosphere {
  /** 0 at night, 1 at midday. */
  daylight: number;
  /** 1 deep at night, 0 by day; drives stars, fireflies and the pond glow. */
  night: number;
  sunDirection: THREE.Vector3;
  sunColor: THREE.Color;
  sunIntensity: number;
  skyTop: THREE.Color;
  skyHorizon: THREE.Color;
  hemiSky: THREE.Color;
  hemiGround: THREE.Color;
  hemiIntensity: number;
  fog: THREE.Color;
}

interface Key {
  hour: number;
  top: string;
  horizon: string;
  sun: string;
  sunIntensity: number;
  hemi: number;
}

// Mythic-modern palette: deep indigo nights, peach dawns, clear teal days, ember dusks.
const KEYS: Key[] = [
  { hour: 0, top: "#050816", horizon: "#141c3a", sun: "#7f9cff", sunIntensity: 0.35, hemi: 0.56 },
  { hour: 5, top: "#0b1230", horizon: "#2a2850", sun: "#8fa6ff", sunIntensity: 0.35, hemi: 0.64 },
  { hour: 6.5, top: "#2a3f7a", horizon: "#f2a68a", sun: "#ffb88a", sunIntensity: 1.1, hemi: 0.96 },
  { hour: 9, top: "#3d7fc4", horizon: "#bfe3f2", sun: "#fff1d6", sunIntensity: 2.2, hemi: 1.44 },
  { hour: 13, top: "#3a86c8", horizon: "#cdeef5", sun: "#ffffff", sunIntensity: 2.6, hemi: 1.6 },
  { hour: 17, top: "#3b6fb0", horizon: "#f6d3a0", sun: "#ffd9a0", sunIntensity: 2, hemi: 1.36 },
  { hour: 19, top: "#2a2f6a", horizon: "#f2a65a", sun: "#ff9e6a", sunIntensity: 1.1, hemi: 0.96 },
  {
    hour: 20.5,
    top: "#0e1433",
    horizon: "#3a2f5a",
    sun: "#8fa6ff",
    sunIntensity: 0.45,
    hemi: 0.64,
  },
  { hour: 24, top: "#050816", horizon: "#141c3a", sun: "#7f9cff", sunIntensity: 0.35, hemi: 0.56 },
];

const lerpColor = (a: string, b: string, t: number) =>
  new THREE.Color(a).lerp(new THREE.Color(b), t);

export function atmosphereAt(hour: number): Atmosphere {
  const h = ((hour % 24) + 24) % 24;
  let i = 0;
  while (i < KEYS.length - 2 && h >= KEYS[i + 1]!.hour) i++;
  const a = KEYS[i]!;
  const b = KEYS[i + 1]!;
  const t = (h - a.hour) / (b.hour - a.hour);

  // Sun arcs from east (6:00) through zenith-ish (12:00) to west (18:00); a moon takes over at night.
  const dayPhase = ((h - 6) / 12) * Math.PI;
  const elevation = Math.sin(dayPhase);
  const daylight = THREE.MathUtils.smoothstep(elevation, -0.1, 0.35);
  const night = 1 - THREE.MathUtils.smoothstep(elevation, -0.2, 0.12);
  const sunDirection =
    elevation > -0.05
      ? new THREE.Vector3(Math.cos(dayPhase), Math.max(0.12, elevation), 0.45).normalize()
      : new THREE.Vector3(-0.4, 0.8, -0.45).normalize(); // moonlight

  const skyTop = lerpColor(a.top, b.top, t);
  const skyHorizon = lerpColor(a.horizon, b.horizon, t);
  return {
    daylight,
    night,
    sunDirection,
    sunColor: lerpColor(a.sun, b.sun, t),
    sunIntensity: THREE.MathUtils.lerp(a.sunIntensity, b.sunIntensity, t),
    skyTop,
    skyHorizon,
    hemiSky: skyTop.clone().lerp(new THREE.Color("#ffffff"), 0.35),
    hemiGround: new THREE.Color("#2b3456").lerp(new THREE.Color("#5fbf8a"), 0.6 * daylight),
    hemiIntensity: THREE.MathUtils.lerp(a.hemi, b.hemi, t),
    fog: skyHorizon.clone().lerp(skyTop, 0.35),
  };
}

/** The current local time as fractional hours. */
export function localHour(date = new Date()): number {
  return date.getHours() + date.getMinutes() / 60;
}
