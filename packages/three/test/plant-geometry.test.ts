import { describe, expect, it } from "vitest";

import { PLANT_PARTS } from "../src/model/growth";
import { plantHeight } from "../src/scene/anchors";
import { buildPlantShape } from "../src/scene/plantGeometry";

describe("buildPlantShape", () => {
  const shape = buildPlantShape(1234, { grove: "#6fd39c" });

  it("builds every part with growth attributes in range", () => {
    for (const part of PLANT_PARTS) {
      const g = shape.parts[part];
      const grow = g.getAttribute("aGrow");
      expect(grow.count).toBeGreaterThan(0);
      expect(g.getAttribute("aSpine").count).toBe(grow.count);
      expect(g.getAttribute("aAttach").count).toBe(grow.count);
      for (let i = 0; i < grow.count; i++) {
        expect(grow.getX(i)).toBeGreaterThanOrEqual(0);
        expect(grow.getX(i)).toBeLessThanOrEqual(1);
      }
    }
  });

  it("is deterministic per seed and matches the anchor height", () => {
    const again = buildPlantShape(1234, { grove: "#6fd39c" });
    expect(Array.from(again.parts.stem.getAttribute("position").array)).toEqual(
      Array.from(shape.parts.stem.getAttribute("position").array),
    );
    expect(shape.height).toBe(plantHeight(1234));
    expect(buildPlantShape(99, { grove: "#6fd39c" }).height).not.toBe(shape.height);
  });

  it("grows the stem from the ground up", () => {
    const stem = shape.parts.stem;
    const grow = stem.getAttribute("aGrow");
    const spine = stem.getAttribute("aSpine");
    let low = Infinity;
    let high = -Infinity;
    for (let i = 0; i < grow.count; i++) {
      if (grow.getX(i) === 0) low = Math.min(low, spine.getY(i));
      if (grow.getX(i) === 1) high = Math.max(high, spine.getY(i));
    }
    expect(low).toBeCloseTo(0, 5);
    expect(high).toBeCloseTo(shape.height, 1);
  });
});
