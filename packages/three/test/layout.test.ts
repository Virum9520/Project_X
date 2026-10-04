import type { GardenSnapshot } from "@sg/contracts";
import { describe, expect, it } from "vitest";

import { generateGardenLayout, layoutKey, prerequisiteDepths } from "../src/generator/layout";
import { createRng, hashString } from "../src/generator/random";
import { MOCK_REVISIONS, mockGardenSnapshot } from "../src/mock/garden";

const final = mockGardenSnapshot();

describe("random", () => {
  it("is deterministic per seed", () => {
    const a = createRng("seed");
    const b = createRng("seed");
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
    expect(createRng("other")()).not.toEqual(createRng("seed")());
    expect(hashString("abc")).toBe(hashString("abc"));
  });
});

describe("generateGardenLayout", () => {
  const layout = generateGardenLayout(final);

  it("places every plant and grove", () => {
    expect(layout.plants.size).toBe(final.plants.length);
    expect(layout.groves.map((g) => g.id)).toEqual(final.groves.map((g) => g.id));
    for (const grove of layout.groves) {
      expect(grove.conceptIds.length).toBe(
        final.plants.filter((p) => p.groveId === grove.id).length,
      );
    }
  });

  it("is deterministic for the same snapshot and seed", () => {
    const again = generateGardenLayout(mockGardenSnapshot());
    expect([...again.plants.values()]).toEqual([...layout.plants.values()]);
    expect(again.paths).toEqual(layout.paths);
  });

  it("keeps plants in place across revisions (placement ignores scores)", () => {
    const early = generateGardenLayout(mockGardenSnapshot(1));
    for (const [id, plant] of layout.plants) {
      expect(early.plants.get(id)?.position).toEqual(plant.position);
    }
    expect(layoutKey(mockGardenSnapshot(1))).toBe(layoutKey(final));
  });

  it("changes with the seed", () => {
    const other = generateGardenLayout(final, { seed: "another-learner" });
    const first = final.plants[0]!.conceptId;
    expect(other.plants.get(first)?.position).not.toEqual(layout.plants.get(first)?.position);
  });

  it("keeps plants on the island, out of the pond and apart from each other", () => {
    const plants = [...layout.plants.values()];
    for (const plant of plants) {
      const [x, y, z] = plant.position;
      const r = Math.hypot(x, z);
      expect(r).toBeLessThan(layout.islandRadius - 1);
      expect(r).toBeGreaterThan(layout.pondRadius * 1.2);
      expect(y).toBeCloseTo(layout.terrain(x, z), 6);
    }
    for (let i = 0; i < plants.length; i++) {
      for (let j = i + 1; j < plants.length; j++) {
        const [ax, , az] = plants[i]!.position;
        const [bx, , bz] = plants[j]!.position;
        expect(Math.hypot(ax - bx, az - bz)).toBeGreaterThan(0.6);
      }
    }
  });

  it("does not overlap groves", () => {
    for (let i = 0; i < layout.groves.length; i++) {
      for (let j = i + 1; j < layout.groves.length; j++) {
        const a = layout.groves[i]!;
        const b = layout.groves[j]!;
        const d = Math.hypot(a.center[0] - b.center[0], a.center[2] - b.center[2]);
        expect(d).toBeGreaterThan(a.radius + b.radius);
      }
    }
  });

  it("puts foundations at the grove's heart", () => {
    for (const grove of layout.groves) {
      const depths = grove.conceptIds.map((id) => layout.plants.get(id)!.depth);
      expect(depths).toEqual([...depths].sort((a, b) => a - b));
    }
  });

  it("draws one path per valid prerequisite edge, starting and ending at the plants", () => {
    expect(layout.paths.length).toBe(final.prerequisites.length);
    for (const path of layout.paths) {
      const from = layout.plants.get(path.from)!.position;
      const to = layout.plants.get(path.to)!.position;
      expect(path.points[0]![0]).toBeCloseTo(from[0]);
      expect(path.points.at(-1)![2]).toBeCloseTo(to[2]);
      expect(path.crossGrove).toBe(
        layout.plants.get(path.from)!.groveId !== layout.plants.get(path.to)!.groveId,
      );
    }
  });

  it("ignores dangling edges, self-loops, cycles and unknown groves", () => {
    const messy: GardenSnapshot = {
      ...final,
      plants: [
        ...final.plants,
        { ...final.plants[0]!, conceptId: "orphan", groveId: "no-such-grove" },
      ],
      prerequisites: [
        ...final.prerequisites,
        { from: "missing", to: final.plants[0]!.conceptId },
        { from: final.plants[0]!.conceptId, to: final.plants[0]!.conceptId },
        { from: "dsa.graphs", to: "dsa.arrays" }, // closes a cycle
      ],
    };
    const result = generateGardenLayout(messy);
    expect(result.plants.has("orphan")).toBe(false);
    expect(result.paths.length).toBe(final.prerequisites.length + 1);
    expect(prerequisiteDepths(messy).get("dsa.dynamic-programming")).toBeGreaterThan(0);
  });

  it("handles an empty garden", () => {
    const empty = generateGardenLayout({ ...final, groves: [], plants: [], prerequisites: [] });
    expect(empty.plants.size).toBe(0);
    expect(empty.islandRadius).toBeGreaterThan(0);
  });

  it("covers every mock revision", () => {
    expect(mockGardenSnapshot(MOCK_REVISIONS + 5).revision).toBe(MOCK_REVISIONS);
  });
});
