import type { GardenSnapshot } from "@sg/contracts";

import { createRng, hashString, range } from "./random";
import { createTerrain, type Terrain } from "./terrain";

/**
 * Garden generator: turns a garden snapshot into deterministic world-space placement.
 *
 * Placement depends only on the snapshot's *structure* (grove ids, concept ids, prerequisite edges)
 * and the seed, never on scores. Plants therefore stay put across revisions and only their growth
 * animates. Snapshots list every curriculum concept (unassessed ones as dormant seeds), so the
 * structure is stable for a given curriculum version.
 */

export type Vec3 = [number, number, number];

export interface GroveLayout {
  id: string;
  label: string;
  index: number;
  /** Center on the island's top surface. */
  center: Vec3;
  radius: number;
  /** Angle (radians) of the grove around the island's center. */
  angle: number;
  color: string;
  /** Concept ids in slot order: foundations at the grove's heart, advanced concepts outward. */
  conceptIds: string[];
  /** Where the grove's elder tree stands, between the grove and the pond. */
  elderTree: Vec3;
}

export interface PlantLayout {
  conceptId: string;
  groveId: string;
  /** Slot index inside the grove (0 = grove center). */
  slot: number;
  position: Vec3;
  /** Yaw in radians. */
  rotation: number;
  /** Uniform scale applied to the plant model. */
  scale: number;
  /** Per-plant seed for its procedural shape. */
  seed: number;
  /** Longest prerequisite chain below this concept. */
  depth: number;
}

export interface PathLayout {
  from: string;
  to: string;
  crossGrove: boolean;
  /** Polyline hugging the terrain, from the prerequisite to the dependent concept. */
  points: Vec3[];
}

export interface GardenLayout {
  seed: string;
  islandRadius: number;
  pondRadius: number;
  /** Water surface height in the pond. */
  waterLevel: number;
  terrain: Terrain;
  groves: GroveLayout[];
  groveById: Map<string, GroveLayout>;
  plants: Map<string, PlantLayout>;
  paths: PathLayout[];
}

export interface LayoutOptions {
  seed?: string;
}

/** Grove palette, tuned to the Skill Garden tokens (moss, glow, bloom, ember). */
export const GROVE_COLORS = [
  "#6fd39c",
  "#9be7ff",
  "#f4b8d4",
  "#f2c46d",
  "#b9a4ff",
  "#7fe0c9",
  "#ff9e8a",
  "#c6e06f",
];

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
/** Plants are modeled about 1.2 units tall; this scales them up relative to the island. */
const PLANT_SCALE = 1.5;
/** Spacing constant of the phyllotaxis spiral (neighbors end up roughly this far apart). */
const PLANT_SPACING = 1.65;
const POND_RADIUS = 2.4;
const PATH_SAMPLES = 28;

/** Longest prerequisite chain under each concept, ignoring cycles and unknown ids. */
export function prerequisiteDepths(snapshot: GardenSnapshot): Map<string, number> {
  const ids = new Set(snapshot.plants.map((p) => p.conceptId));
  const parents = new Map<string, string[]>();
  for (const edge of snapshot.prerequisites) {
    if (!ids.has(edge.from) || !ids.has(edge.to) || edge.from === edge.to) continue;
    parents.set(edge.to, [...(parents.get(edge.to) ?? []), edge.from]);
  }
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  const visit = (id: string): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (visiting.has(id)) return 0; // cycle: treat the back edge as absent
    visiting.add(id);
    let d = 0;
    for (const parent of parents.get(id) ?? []) d = Math.max(d, visit(parent) + 1);
    visiting.delete(id);
    depth.set(id, d);
    return d;
  };
  for (const id of ids) visit(id);
  return depth;
}

function groveRadius(count: number): number {
  return PLANT_SPACING * Math.sqrt(Math.max(1, count)) + 1;
}

export function generateGardenLayout(
  snapshot: GardenSnapshot,
  { seed = "skill-garden" }: LayoutOptions = {},
): GardenLayout {
  const depths = prerequisiteDepths(snapshot);
  const groveIds = new Set(snapshot.groves.map((g) => g.id));
  const plantsByGrove = new Map<string, string[]>();
  for (const plant of snapshot.plants) {
    if (!groveIds.has(plant.groveId)) continue;
    plantsByGrove.set(plant.groveId, [
      ...(plantsByGrove.get(plant.groveId) ?? []),
      plant.conceptId,
    ]);
  }

  // Ring of groves around the central pond, wide enough that neighbors never overlap.
  const n = Math.max(1, snapshot.groves.length);
  const radii = snapshot.groves.map((g) => groveRadius(plantsByGrove.get(g.id)?.length ?? 0));
  const maxRadius = Math.max(1, ...radii);
  const gap = 0.9;
  const ringForNeighbors = n > 1 ? (2 * maxRadius + gap) / (2 * Math.sin(Math.PI / n)) : 0;
  const ring = Math.max(POND_RADIUS + maxRadius + 1.2, ringForNeighbors);
  const islandRadius = ring + maxRadius + 1.8;
  const terrain = createTerrain({ seed, radius: islandRadius, pondRadius: POND_RADIUS });
  const at = (x: number, z: number): Vec3 => [x, terrain(x, z), z];

  const rng = createRng(`${seed}:groves`);
  const startAngle = range(rng, 0, Math.PI * 2);

  const plants = new Map<string, PlantLayout>();
  const groves: GroveLayout[] = snapshot.groves.map((grove, index) => {
    const angle = startAngle + (index / n) * Math.PI * 2 + range(rng, -0.08, 0.08);
    const cx = Math.cos(angle) * ring;
    const cz = Math.sin(angle) * ring;
    const radius = radii[index] ?? groveRadius(0);

    const conceptIds = [...(plantsByGrove.get(grove.id) ?? [])].sort(
      (a, b) => (depths.get(a) ?? 0) - (depths.get(b) ?? 0) || (a < b ? -1 : a > b ? 1 : 0),
    );
    conceptIds.forEach((conceptId, slot) => {
      const plantRng = createRng(`${seed}:${conceptId}`);
      const r = PLANT_SPACING * Math.sqrt(slot + 0.35);
      const theta = angle + slot * GOLDEN_ANGLE;
      const jitter = 0.14;
      const x = cx + Math.cos(theta) * r + range(plantRng, -jitter, jitter);
      const z = cz + Math.sin(theta) * r + range(plantRng, -jitter, jitter);
      plants.set(conceptId, {
        conceptId,
        groveId: grove.id,
        slot,
        position: at(x, z),
        rotation: range(plantRng, 0, Math.PI * 2),
        scale: PLANT_SCALE * range(plantRng, 0.9, 1.1),
        seed: hashString(`${seed}:${conceptId}`),
        depth: depths.get(conceptId) ?? 0,
      });
    });

    // The elder tree stands on the pond side, behind the grove as seen from the grove camera.
    const inward = Math.max(0, ring - radius - 0.9);
    return {
      id: grove.id,
      label: grove.label,
      index,
      center: at(cx, cz),
      radius,
      angle,
      color: GROVE_COLORS[index % GROVE_COLORS.length] ?? "#6fd39c",
      conceptIds,
      elderTree: at(Math.cos(angle) * inward, Math.sin(angle) * inward),
    };
  });

  const paths: PathLayout[] = [];
  for (const edge of snapshot.prerequisites) {
    const a = plants.get(edge.from);
    const b = plants.get(edge.to);
    if (!a || !b || a === b) continue;
    const crossGrove = a.groveId !== b.groveId;
    const pathRng = createRng(`${seed}:path:${edge.from}->${edge.to}`);
    const [ax, , az] = a.position;
    const [bx, , bz] = b.position;
    const mx = (ax + bx) / 2;
    const mz = (az + bz) / 2;
    // Cross-grove roots bow toward the pond; local ones get a gentle sideways curve.
    const pull = crossGrove ? 0.35 : 0;
    const dx = bx - ax;
    const dz = bz - az;
    const bend = range(pathRng, -0.18, 0.18);
    const qx = mx * (1 - pull) - dz * bend;
    const qz = mz * (1 - pull) + dx * bend;
    const points: Vec3[] = [];
    for (let i = 0; i <= PATH_SAMPLES; i++) {
      const t = i / PATH_SAMPLES;
      const u = 1 - t;
      let x = u * u * ax + 2 * u * t * qx + t * t * bx;
      let z = u * u * az + 2 * u * t * qz + t * t * bz;
      // Keep roots out of the water.
      const d = Math.hypot(x, z);
      if (d < POND_RADIUS * 1.25 && d > 1e-6) {
        x *= (POND_RADIUS * 1.25) / d;
        z *= (POND_RADIUS * 1.25) / d;
      }
      points.push([x, terrain(x, z) + 0.04, z]);
    }
    paths.push({ from: edge.from, to: edge.to, crossGrove, points });
  }

  return {
    seed,
    islandRadius,
    pondRadius: POND_RADIUS,
    waterLevel: terrain(0, 0) + 0.32,
    terrain,
    groves,
    groveById: new Map(groves.map((g) => [g.id, g])),
    plants,
    paths,
  };
}

/** Stable key for a snapshot's structure; the layout only needs regenerating when it changes. */
export function layoutKey(snapshot: GardenSnapshot, seed = "skill-garden"): string {
  const groves = snapshot.groves.map((g) => `${g.id}=${g.label}`).join(",");
  const plants = snapshot.plants.map((p) => `${p.groveId}/${p.conceptId}`).join(",");
  const edges = snapshot.prerequisites.map((e) => `${e.from}>${e.to}`).join(",");
  return `${seed}|${groves}|${plants}|${edges}`;
}
