import type { GardenSnapshot, PlantPart } from "@sg/contracts";

import type { GardenLayout } from "../generator/layout";
import { PART_TO_DIMENSION, PLANT_PARTS } from "./growth";
import type { GardenFocus } from "./types";

/** Pure semantic-zoom navigation: Esc zooms out, arrows move between siblings, Enter zooms in. */

export const GARDEN_FOCUS: GardenFocus = { level: "garden" };

export function focusGroveId(focus: GardenFocus, layout: GardenLayout): string | null {
  if (focus.level === "garden") return null;
  if (focus.level === "grove") return focus.groveId;
  return layout.plants.get(focus.conceptId)?.groveId ?? null;
}

export function focusConceptId(focus: GardenFocus): string | null {
  return focus.level === "plant" || focus.level === "part" ? focus.conceptId : null;
}

/** One level up: Part → Plant → Grove → Garden. */
export function zoomOut(focus: GardenFocus, layout: GardenLayout): GardenFocus {
  switch (focus.level) {
    case "garden":
      return focus;
    case "grove":
      return GARDEN_FOCUS;
    case "plant": {
      const groveId = focusGroveId(focus, layout);
      return groveId ? { level: "grove", groveId } : GARDEN_FOCUS;
    }
    case "part":
      return { level: "plant", conceptId: focus.conceptId };
  }
}

/** One level down, into the first child: first grove, its central plant, then the roots. */
export function zoomIn(focus: GardenFocus, layout: GardenLayout): GardenFocus {
  switch (focus.level) {
    case "garden": {
      const grove = layout.groves[0];
      return grove ? { level: "grove", groveId: grove.id } : focus;
    }
    case "grove": {
      const conceptId = layout.groveById.get(focus.groveId)?.conceptIds[0];
      return conceptId ? { level: "plant", conceptId } : focus;
    }
    case "plant":
      return { level: "part", conceptId: focus.conceptId, part: "roots" };
    case "part":
      return focus;
  }
}

function step<T>(items: readonly T[], current: T, delta: number): T {
  const index = items.indexOf(current);
  if (index < 0 || items.length === 0) return current;
  return items[(((index + delta) % items.length) + items.length) % items.length] ?? current;
}

/** Next (`delta` = 1) or previous (-1) sibling at the same level, wrapping around. */
export function moveSibling(focus: GardenFocus, layout: GardenLayout, delta: number): GardenFocus {
  switch (focus.level) {
    case "garden":
      return focus;
    case "grove": {
      const ids = layout.groves.map((g) => g.id);
      return { level: "grove", groveId: step(ids, focus.groveId, delta) };
    }
    case "plant": {
      const groveId = focusGroveId(focus, layout);
      const ids = (groveId && layout.groveById.get(groveId)?.conceptIds) || [];
      return { level: "plant", conceptId: step(ids, focus.conceptId, delta) };
    }
    case "part":
      return { ...focus, part: step(PLANT_PARTS, focus.part, delta) };
  }
}

export function focusEquals(a: GardenFocus, b: GardenFocus): boolean {
  return focusToString(a) === focusToString(b);
}

/** Compact string form for URLs: `garden`, `grove:dsa`, `plant:dsa.graphs`, `part:dsa.graphs:roots`. */
export function focusToString(focus: GardenFocus): string {
  switch (focus.level) {
    case "garden":
      return "garden";
    case "grove":
      return `grove:${focus.groveId}`;
    case "plant":
      return `plant:${focus.conceptId}`;
    case "part":
      return `part:${focus.conceptId}:${focus.part}`;
  }
}

/** Inverse of `focusToString`; anything unrecognized falls back to the whole garden. */
export function focusFromString(value: string | null | undefined): GardenFocus {
  if (!value) return GARDEN_FOCUS;
  const [level, id, part] = value.split(":");
  if (level === "grove" && id) return { level, groveId: id };
  if (level === "plant" && id) return { level, conceptId: id };
  if (level === "part" && id && PLANT_PARTS.includes(part as PlantPart)) {
    return { level, conceptId: id, part: part as PlantPart };
  }
  return GARDEN_FOCUS;
}

/** Drops focus on groves or concepts that are not in the layout (e.g. after a filter change). */
export function sanitizeFocus(focus: GardenFocus, layout: GardenLayout): GardenFocus {
  if (focus.level === "grove") return layout.groveById.has(focus.groveId) ? focus : GARDEN_FOCUS;
  if (focus.level === "plant" || focus.level === "part") {
    return layout.plants.has(focus.conceptId) ? focus : GARDEN_FOCUS;
  }
  return focus;
}

/** Ordered path from the garden down to `focus`, for breadcrumbs. */
export function focusTrail(focus: GardenFocus, layout: GardenLayout): GardenFocus[] {
  const trail: GardenFocus[] = [focus];
  let current = focus;
  while (current.level !== "garden") {
    current = zoomOut(current, layout);
    trail.unshift(current);
  }
  return trail;
}

/** Short human label for one focus (no ancestors). */
export function focusLabel(focus: GardenFocus, snapshot: GardenSnapshot): string {
  switch (focus.level) {
    case "garden":
      return "Garden";
    case "grove":
      return snapshot.groves.find((g) => g.id === focus.groveId)?.label ?? focus.groveId;
    case "plant":
      return snapshot.plants.find((p) => p.conceptId === focus.conceptId)?.label ?? focus.conceptId;
    case "part":
      return `${focus.part[0]?.toUpperCase()}${focus.part.slice(1)} (${PART_TO_DIMENSION[focus.part]})`;
  }
}

/** Sentence for screen readers announcing the current focus. */
export function describeFocus(focus: GardenFocus, snapshot: GardenSnapshot): string {
  switch (focus.level) {
    case "garden":
      return `Whole garden: ${snapshot.groves.length} groves, ${snapshot.plants.length} concepts.`;
    case "grove": {
      const count = snapshot.plants.filter((p) => p.groveId === focus.groveId).length;
      return `${focusLabel(focus, snapshot)} grove, ${count} concepts.`;
    }
    case "plant": {
      const plant = snapshot.plants.find((p) => p.conceptId === focus.conceptId);
      return plant
        ? `${plant.label}: ${plant.status}, ${plant.evidenceCount} evidence items.`
        : focus.conceptId;
    }
    case "part": {
      const plant = snapshot.plants.find((p) => p.conceptId === focus.conceptId);
      const score = plant?.dimensions[PART_TO_DIMENSION[focus.part]];
      const pct = (v: number) => `${Math.round(v * 100)}%`;
      return score
        ? `${plant?.label} ${focusLabel(focus, snapshot)}: independent ${pct(score.independent)}, assisted ${pct(score.assisted)}.`
        : focusLabel(focus, snapshot);
    }
  }
}
