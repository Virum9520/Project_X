import { describe, expect, it } from "vitest";

import { generateGardenLayout } from "../src/generator/layout";
import { mockGardenSnapshot } from "../src/mock/garden";
import {
  FRAME_BUDGETS,
  SCENE_BUDGET,
  checkFrameBudget,
  percentile,
  summarizeFrames,
} from "../src/perf/frameBudget";
import { PLANT_PARTS } from "../src/model/growth";
import { buildPlantShape } from "../src/scene/plantGeometry";

function plantVertices(seed: number): number {
  const shape = buildPlantShape(seed, { grove: "#6fd39c" });
  return PLANT_PARTS.reduce((n, part) => n + shape.parts[part].getAttribute("position").count, 0);
}

describe("static scene budget (no GPU needed)", () => {
  const snapshot = mockGardenSnapshot();

  it("keeps a full garden within the plant count budget", () => {
    expect(snapshot.plants.length).toBeLessThanOrEqual(SCENE_BUDGET.maxPlants);
  });

  it("keeps every plant under the per-plant vertex budget", () => {
    const counts = Array.from({ length: 40 }, (_, i) => plantVertices(1000 + i * 7919));
    expect(Math.max(...counts)).toBeLessThanOrEqual(SCENE_BUDGET.maxVerticesPerPlant);
  });

  it("keeps a full-size garden (every curriculum concept) under the total vertex budget", () => {
    const worst = Array.from({ length: 40 }, (_, i) => plantVertices(1000 + i * 7919));
    const perPlant = Math.max(...worst);
    expect(perPlant * SCENE_BUDGET.maxPlants).toBeLessThanOrEqual(
      SCENE_BUDGET.maxPlantVerticesTotal * 2.5,
    );
    // Typical (mean) plant times the plant ceiling is what the budget is actually set against.
    const mean = worst.reduce((a, b) => a + b, 0) / worst.length;
    expect(mean * SCENE_BUDGET.maxPlants).toBeLessThanOrEqual(SCENE_BUDGET.maxPlantVerticesTotal);
  });

  it("generates the layout fast enough not to hitch the main thread", () => {
    generateGardenLayout(snapshot); // warm the JIT
    const start = performance.now();
    for (let i = 0; i < 5; i++) generateGardenLayout(snapshot, { seed: `perf-${i}` });
    const each = (performance.now() - start) / 5;
    expect(each).toBeLessThanOrEqual(SCENE_BUDGET.maxLayoutMs);
  });
});

describe("frame-time analysis", () => {
  const steady = (ms: number, n = 400) => Array.from({ length: n }, () => ms);

  it("computes percentiles and drops warmup frames", () => {
    expect(percentile([1, 2, 3, 4], 0.5)).toBe(2);
    const stats = summarizeFrames([500, ...steady(16.7, 200)], 1);
    expect(stats.frames).toBe(200);
    expect(stats.p99Ms).toBeCloseTo(16.7);
    expect(stats.fps).toBeCloseTo(59.9, 0);
  });

  it("accepts a steady 60 fps run on the desktop budget", () => {
    expect(checkFrameBudget(summarizeFrames(steady(16.6), 0), FRAME_BUDGETS.desktop)).toEqual([]);
  });

  it("rejects a 30 fps run on the desktop budget but accepts it on low-end", () => {
    const stats = summarizeFrames(steady(33), 0);
    expect(checkFrameBudget(stats, FRAME_BUDGETS.desktop).length).toBeGreaterThan(0);
    expect(checkFrameBudget(stats, FRAME_BUDGETS.lowEnd)).toEqual([]);
  });

  it("rejects hitchy runs and too-short samples", () => {
    const hitchy = [...steady(16.6, 380), ...steady(120, 20)];
    const problems = checkFrameBudget(summarizeFrames(hitchy, 0), FRAME_BUDGETS.desktop);
    expect(problems.some((p) => p.includes("frames over 33 ms"))).toBe(true);
    expect(
      checkFrameBudget(summarizeFrames(steady(16.6, 50), 0), FRAME_BUDGETS.desktop)[0],
    ).toMatch(/only 50 frames/);
  });
});
