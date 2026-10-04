import { describe, expect, it } from "vitest";

import { generateGardenLayout } from "../src/generator/layout";
import { mockGardenSnapshot } from "../src/mock/garden";
import { plantGrowth, PLANT_PARTS } from "../src/model/growth";
import type { GardenFocus } from "../src/model/types";
import { partAnchor, plantHeight } from "../src/scene/anchors";
import { atmosphereAt } from "../src/scene/atmosphere";
import { framingFor } from "../src/scene/framing";

const snapshot = mockGardenSnapshot();
const layout = generateGardenLayout(snapshot);
const growth = new Map(snapshot.plants.map((p) => [p.conceptId, plantGrowth(p)]));

describe("atmosphere", () => {
  it("is bright at noon and dark at midnight", () => {
    expect(atmosphereAt(12).daylight).toBeGreaterThan(0.9);
    expect(atmosphereAt(12).night).toBe(0);
    expect(atmosphereAt(0).daylight).toBe(0);
    expect(atmosphereAt(0).night).toBe(1);
    expect(atmosphereAt(24 + 12).daylight).toBeCloseTo(atmosphereAt(12).daylight);
  });
});

describe("camera framing", () => {
  const plant = snapshot.plants.find((p) => p.status === "retained")!;
  const foci: GardenFocus[] = [
    { level: "garden" },
    { level: "grove", groveId: plant.groveId },
    { level: "plant", conceptId: plant.conceptId },
    ...PLANT_PARTS.map((part) => ({ level: "part" as const, conceptId: plant.conceptId, part })),
  ];

  it("places the camera above and away from its target at every level", () => {
    let previous = Number.POSITIVE_INFINITY;
    for (const focus of foci.slice(0, 3)) {
      const { position, target } = framingFor(focus, layout, (id) => growth.get(id));
      const distance = position.distanceTo(target);
      expect(position.y).toBeGreaterThan(target.y);
      expect(distance).toBeLessThan(previous); // each level zooms in closer
      previous = distance;
    }
    for (const focus of foci.slice(3)) {
      const { position, target } = framingFor(focus, layout, (id) => growth.get(id));
      expect(Number.isFinite(position.length()) && Number.isFinite(target.length())).toBe(true);
    }
  });

  it("falls back to the overview for unknown targets", () => {
    const overview = framingFor({ level: "garden" }, layout, (id) => growth.get(id));
    const missing = framingFor({ level: "plant", conceptId: "nope" }, layout, (id) =>
      growth.get(id),
    );
    expect(missing.position.equals(overview.position)).toBe(true);
  });

  it("stacks part anchors bottom to top", () => {
    const placed = layout.plants.get(plant.conceptId)!;
    const ys = PLANT_PARTS.map((part) => partAnchor(placed, part, growth.get(plant.conceptId)!).y);
    expect(ys).toEqual([...ys].sort((a, b) => a - b));
    expect(plantHeight(placed.seed)).toBeGreaterThan(1);
  });
});
