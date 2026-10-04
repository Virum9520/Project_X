import {
  DIMENSION_TO_PART,
  type Dimension,
  type PlantPart,
  type PlantSnapshot,
} from "@sg/contracts";

/** Plant parts in the order they grow, bottom to top. */
export const PLANT_PARTS: readonly PlantPart[] = ["roots", "stem", "branches", "blossoms"];

export const PART_TO_DIMENSION = Object.fromEntries(
  Object.entries(DIMENSION_TO_PART).map(([dimension, part]) => [part, dimension]),
) as Record<PlantPart, Dimension>;

/**
 * How far one part has grown, as fractions of its full length. Always `solid ≤ confirmed ≤ total`:
 * - `solid`: backed by independent evidence (opaque).
 * - `confirmed`: backed by any confirmed evidence; the gap above `solid` is assisted ghost growth.
 * - `total`: what is drawn; the gap above `confirmed` is glowing provisional growth from a live session.
 */
export interface PartGrowth {
  solid: number;
  confirmed: number;
  total: number;
}

export interface PlantGrowth {
  parts: Record<PlantPart, PartGrowth>;
  /** 0 = healthy, 1 = fully wilted (review overdue). */
  wilt: number;
  /** No evidence yet: the plant is a dormant seed. */
  dormant: boolean;
}

/** Explanation evidence alone makes a small sprout so the plant "visibly sprouts". */
export const SPROUT_HEIGHT = 0.22;

const WILT_BY_STATUS: Partial<Record<PlantSnapshot["status"], number>> = { due: 0.35, wilting: 1 };

const clamp01 = (value: number) => Math.min(1, Math.max(0, Number.isFinite(value) ? value : 0));

/** Unproven seedling growth per part for a self-rated starting level. Drawn as ghost growth. */
const BASELINE_GROWTH: Record<1 | 2 | 3, Partial<Record<Dimension, number>>> = {
  1: { explanation: 0.3 },
  2: { explanation: 0.5, application: 0.4 },
  3: { explanation: 0.7, application: 0.6, transfer: 0.3 },
};

function partGrowth(plant: PlantSnapshot, dimension: Dimension): PartGrowth {
  const score = plant.dimensions[dimension];
  const solid = clamp01(score.independent);
  const seedling = plant.baselineLevel ? (BASELINE_GROWTH[plant.baselineLevel][dimension] ?? 0) : 0;
  const confirmed = Math.max(solid, clamp01(score.assisted), seedling);
  const total = Math.max(confirmed, clamp01(plant.provisional?.[dimension] ?? 0));
  return { solid, confirmed, total };
}

function atLeast(part: PartGrowth, floor: PartGrowth): PartGrowth {
  return {
    solid: Math.max(part.solid, floor.solid),
    confirmed: Math.max(part.confirmed, floor.confirmed),
    total: Math.max(part.total, floor.total),
  };
}

/** Maps a plant's evidence scores to the growth the scene draws. Pure, so it is unit-tested. */
export function plantGrowth(plant: PlantSnapshot): PlantGrowth {
  const roots = partGrowth(plant, "explanation");
  // Any explanation evidence raises a sprout, with the same solid/ghost/provisional split.
  const sprout: PartGrowth = {
    solid: roots.solid > 0 ? SPROUT_HEIGHT : 0,
    confirmed: roots.confirmed > 0 ? SPROUT_HEIGHT : 0,
    total: roots.total > 0 ? SPROUT_HEIGHT : 0,
  };
  const parts: Record<PlantPart, PartGrowth> = {
    roots,
    stem: atLeast(partGrowth(plant, "application"), sprout),
    branches: partGrowth(plant, "transfer"),
    blossoms: partGrowth(plant, "retention"),
  };
  const dormant = PLANT_PARTS.every((part) => parts[part].total === 0);
  return { parts, wilt: WILT_BY_STATUS[plant.status] ?? 0, dormant };
}

/** Mean confirmed growth across the four dimensions, in [0, 1]. */
export function plantVigor(plant: PlantSnapshot): number {
  const g = plantGrowth(plant);
  return PLANT_PARTS.reduce((sum, part) => sum + g.parts[part].confirmed, 0) / PLANT_PARTS.length;
}
