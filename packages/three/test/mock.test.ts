import { PLANT_STATUSES } from "@sg/contracts";
import { describe, expect, it } from "vitest";

import { PLANT_PARTS } from "../src/model/growth";
import {
  MOCK_REVISIONS,
  mockEvidence,
  mockGardenHistory,
  mockGardenSnapshot,
  withProvisionalGrowth,
} from "../src/mock/garden";

describe("mock garden", () => {
  const history = mockGardenHistory();
  const final = history.at(-1)!;

  it("starts empty and grows monotonically until reviews fall due", () => {
    expect(history).toHaveLength(MOCK_REVISIONS + 1);
    expect(history[0]!.plants.every((p) => p.status === "unassessed")).toBe(true);
    for (let i = 1; i < history.length; i++) {
      const before = history[i - 1]!;
      const after = history[i]!;
      after.plants.forEach((plant, j) => {
        const prev = before.plants[j]!;
        expect(plant.evidenceCount).toBeGreaterThanOrEqual(prev.evidenceCount);
      });
    }
  });

  it("ends on a mix of every status", () => {
    const statuses = new Set(final.plants.map((p) => p.status));
    for (const status of PLANT_STATUSES) expect(statuses).toContain(status);
  });

  it("only references real plants in prerequisite edges", () => {
    const ids = new Set(final.plants.map((p) => p.conceptId));
    for (const edge of final.prerequisites) {
      expect(ids).toContain(edge.from);
      expect(ids).toContain(edge.to);
    }
  });

  it("is deterministic", () => {
    expect(mockGardenSnapshot(7)).toEqual(mockGardenSnapshot(7));
  });

  it("returns evidence only for parts that have grown", () => {
    const grown = final.plants.find((p) => p.status === "retained")!;
    for (const part of PLANT_PARTS) {
      const cards = mockEvidence(final, grown.conceptId, part);
      expect(cards.length).toBeGreaterThan(0);
      expect(new Set(cards.map((c) => c.id)).size).toBe(cards.length);
    }
    const dormant = final.plants.find((p) => p.status === "unassessed")!;
    expect(mockEvidence(final, dormant.conceptId, "roots")).toEqual([]);
  });

  it("adds provisional growth without mutating the snapshot", () => {
    const target = final.plants[0]!.conceptId;
    const live = withProvisionalGrowth(final, target, "transfer", 0.8);
    expect(live.plants[0]!.provisional).toEqual({ transfer: 0.8 });
    expect(final.plants[0]!.provisional).toBeUndefined();
  });
});
