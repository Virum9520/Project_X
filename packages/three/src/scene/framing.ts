import * as THREE from "three";

import type { GardenLayout } from "../generator/layout";
import type { PlantGrowth } from "../model/growth";
import type { GardenFocus } from "../model/types";
import { partAnchor, plantCenter } from "./anchors";

export interface Framing {
  position: THREE.Vector3;
  target: THREE.Vector3;
}

const UP = new THREE.Vector3(0, 1, 0);

function outward(x: number, z: number): THREE.Vector3 {
  const v = new THREE.Vector3(x, 0, z);
  return v.lengthSq() > 1e-6 ? v.normalize() : new THREE.Vector3(0, 0, 1);
}

const PART_OFFSET = {
  roots: { out: 1.9, up: 1.7 },
  stem: { out: 2.6, up: 0.5 },
  branches: { out: 2.6, up: 0.8 },
  blossoms: { out: 2.2, up: 1.0 },
} as const;

/** Where the camera sits and looks for each semantic zoom level. */
export function framingFor(
  focus: GardenFocus,
  layout: GardenLayout,
  growthOf: (conceptId: string) => PlantGrowth | undefined,
): Framing {
  const R = layout.islandRadius;
  const overview: Framing = {
    position: new THREE.Vector3(0, 0.72, 1).normalize().multiplyScalar(R * 2.15),
    target: new THREE.Vector3(0, -0.4, 0),
  };
  switch (focus.level) {
    case "garden":
      return overview;
    case "grove": {
      const grove = layout.groveById.get(focus.groveId);
      if (!grove) return overview;
      const [cx, cy, cz] = grove.center;
      const o = outward(cx, cz);
      const target = new THREE.Vector3(cx, cy + 0.5, cz);
      return {
        target,
        position: target
          .clone()
          .addScaledVector(o, grove.radius * 1.55 + 2.6)
          .addScaledVector(UP, grove.radius * 1.05 + 1.9),
      };
    }
    case "plant":
    case "part": {
      const plant = layout.plants.get(focus.conceptId);
      const growth = growthOf(focus.conceptId);
      if (!plant || !growth) return overview;
      const o = outward(plant.position[0], plant.position[2]);
      if (focus.level === "plant") {
        const target = plantCenter(plant, growth);
        return {
          target,
          position: target.clone().addScaledVector(o, 4.6).addScaledVector(UP, 1.9),
        };
      }
      const target = partAnchor(plant, focus.part, growth);
      const offset = PART_OFFSET[focus.part];
      return {
        target,
        position: target.clone().addScaledVector(o, offset.out).addScaledVector(UP, offset.up),
      };
    }
  }
}
