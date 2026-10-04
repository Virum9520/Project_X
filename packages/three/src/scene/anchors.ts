import type { PlantPart } from "@sg/contracts";
import * as THREE from "three";

import type { PlantLayout } from "../generator/layout";
import { createRng, range } from "../generator/random";
import type { PlantGrowth } from "../model/growth";

/** Full-growth stem height for a plant seed (the first draw of `buildPlantShape`'s RNG). */
export function plantHeight(seed: number): number {
  return range(createRng(seed), 1.05, 1.4);
}

/** World-space point the camera frames for one part of a plant, at its target growth. */
export function partAnchor(
  plant: PlantLayout,
  part: PlantPart,
  growth: PlantGrowth,
): THREE.Vector3 {
  const h = plantHeight(plant.seed) * plant.scale;
  const stem = Math.max(growth.parts.stem.total, 0.22);
  const y = {
    roots: 0.06,
    stem: h * stem * 0.5,
    branches: h * Math.max(stem, 0.6) * 0.72,
    blossoms: h * stem + 0.05,
  }[part];
  const [x, py, z] = plant.position;
  return new THREE.Vector3(x, py + y, z);
}

/** World-space center of a whole plant, for plant-level framing. */
export function plantCenter(plant: PlantLayout, growth: PlantGrowth): THREE.Vector3 {
  const h = plantHeight(plant.seed) * plant.scale;
  const [x, y, z] = plant.position;
  return new THREE.Vector3(x, y + h * Math.max(growth.parts.stem.total, 0.3) * 0.5, z);
}

/** World-space top of a plant's stem at its target growth (where its label floats). */
export function plantTop(plant: PlantLayout, growth: PlantGrowth): THREE.Vector3 {
  const h = plantHeight(plant.seed) * plant.scale;
  const [x, y, z] = plant.position;
  return new THREE.Vector3(x, y + h * Math.max(growth.parts.stem.total, 0.22), z);
}
