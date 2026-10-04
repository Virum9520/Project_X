import type { PlantSnapshot } from "@sg/contracts";
import { describe, expect, it } from "vitest";

import { PART_TO_DIMENSION, plantGrowth, plantVigor, SPROUT_HEIGHT } from "../src/model/growth";

const zero = { independent: 0, assisted: 0 };
const plant = (overrides: Partial<PlantSnapshot> = {}): PlantSnapshot => ({
  conceptId: "dsa.graphs",
  groveId: "dsa",
  label: "Graphs",
  status: "unassessed",
  dimensions: { explanation: zero, application: zero, transfer: zero, retention: zero },
  evidenceCount: 0,
  ...overrides,
});

describe("plantGrowth", () => {
  it("maps each dimension to its plant part", () => {
    expect(PART_TO_DIMENSION).toEqual({
      roots: "explanation",
      stem: "application",
      branches: "transfer",
      blossoms: "retention",
    });
  });

  it("leaves an unassessed plant dormant", () => {
    const g = plantGrowth(plant());
    expect(g.dormant).toBe(true);
    expect(g.parts.stem.total).toBe(0);
  });

  it("sprouts on explanation evidence alone", () => {
    const g = plantGrowth(
      plant({
        dimensions: { ...plant().dimensions, explanation: { independent: 0.8, assisted: 0 } },
      }),
    );
    expect(g.dormant).toBe(false);
    expect(g.parts.roots).toEqual({ solid: 0.8, confirmed: 0.8, total: 0.8 });
    expect(g.parts.stem).toEqual({
      solid: SPROUT_HEIGHT,
      confirmed: SPROUT_HEIGHT,
      total: SPROUT_HEIGHT,
    });
  });

  it("keeps assisted growth separate from independent growth (ghost)", () => {
    const g = plantGrowth(
      plant({
        dimensions: { ...plant().dimensions, application: { independent: 0.2, assisted: 0.7 } },
      }),
    );
    expect(g.parts.stem.solid).toBe(0.2);
    expect(g.parts.stem.confirmed).toBe(0.7);
    // An assisted-only sprout is a ghost sprout.
    const ghost = plantGrowth(
      plant({
        dimensions: { ...plant().dimensions, explanation: { independent: 0, assisted: 0.4 } },
      }),
    );
    expect(ghost.parts.stem.solid).toBe(0);
    expect(ghost.parts.stem.confirmed).toBe(SPROUT_HEIGHT);
  });

  it("draws provisional growth above confirmed growth", () => {
    const g = plantGrowth(
      plant({
        dimensions: { ...plant().dimensions, transfer: { independent: 0.3, assisted: 0.3 } },
        provisional: { transfer: 0.9 },
      }),
    );
    expect(g.parts.branches).toEqual({ solid: 0.3, confirmed: 0.3, total: 0.9 });
  });

  it("clamps out-of-range and invalid scores", () => {
    const g = plantGrowth(
      plant({
        dimensions: {
          ...plant().dimensions,
          retention: { independent: 1.7, assisted: Number.NaN },
          transfer: { independent: -1, assisted: 0.5 },
        },
      }),
    );
    expect(g.parts.blossoms).toEqual({ solid: 1, confirmed: 1, total: 1 });
    expect(g.parts.branches.solid).toBe(0);
  });

  it("wilts plants whose review is due or overdue", () => {
    expect(plantGrowth(plant({ status: "retained" })).wilt).toBe(0);
    expect(plantGrowth(plant({ status: "due" })).wilt).toBeGreaterThan(0);
    expect(plantGrowth(plant({ status: "wilting" })).wilt).toBe(1);
  });

  it("computes vigor from confirmed growth", () => {
    const full = { independent: 1, assisted: 0 };
    expect(
      plantVigor(
        plant({
          dimensions: { explanation: full, application: full, transfer: full, retention: full },
        }),
      ),
    ).toBe(1);
    expect(plantVigor(plant())).toBe(0);
  });
});
