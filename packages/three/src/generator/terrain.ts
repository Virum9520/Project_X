import { hashString } from "./random";

/**
 * Island terrain height field. Pure and seeded, so plant placement (CPU) and the island mesh agree
 * on where the ground is.
 */

export interface TerrainOptions {
  seed: string;
  radius: number;
  /** Peak height of the rolling hills on the island's top surface. */
  amplitude?: number;
  /** Radius of the central pond (a shallow dip), or 0 for none. */
  pondRadius?: number;
}

function lattice(seed: number, x: number, z: number): number {
  let h = seed ^ Math.imul(x, 374761393) ^ Math.imul(z, 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

function smooth(t: number): number {
  return t * t * (3 - 2 * t);
}

/** 2D value noise in [0, 1). */
export function valueNoise(seed: number, x: number, z: number): number {
  const x0 = Math.floor(x);
  const z0 = Math.floor(z);
  const tx = smooth(x - x0);
  const tz = smooth(z - z0);
  const a = lattice(seed, x0, z0);
  const b = lattice(seed, x0 + 1, z0);
  const c = lattice(seed, x0, z0 + 1);
  const d = lattice(seed, x0 + 1, z0 + 1);
  return a + (b - a) * tx + (c - a) * tz + (a - b - c + d) * tx * tz;
}

/** Two-octave noise in roughly [-1, 1]. */
function fbm(seed: number, x: number, z: number): number {
  return (
    (valueNoise(seed, x, z) - 0.5) * 1.4 + (valueNoise(seed + 17, x * 2.1, z * 2.1) - 0.5) * 0.6
  );
}

/** Builds `height(x, z)`: the y of the island's top surface at a point. */
export function createTerrain({ seed, radius, amplitude = 0.55, pondRadius = 0 }: TerrainOptions) {
  const s = hashString(seed);
  return function height(x: number, z: number): number {
    const r = Math.hypot(x, z) / radius;
    // Gentle dome so the center sits a little higher than the rim, then a soft lip at the edge.
    const dome = 0.35 * (1 - r * r);
    const hills = amplitude * fbm(s, x * 0.18, z * 0.18) * Math.max(0, 1 - r * 0.6);
    const edge = r > 0.92 ? -(r - 0.92) * 4 : 0;
    let y = dome + hills + edge;
    if (pondRadius > 0) {
      // Flatten the hills around the pond, then dip below the water line inside it.
      const p = Math.hypot(x, z) / pondRadius;
      if (p < 1.8) y -= hills * smooth(Math.min(1, (1.8 - p) / 0.8));
      if (p < 1.15) y -= 0.5 * smooth((1.15 - p) / 1.15);
    }
    return y;
  };
}

export type Terrain = ReturnType<typeof createTerrain>;
