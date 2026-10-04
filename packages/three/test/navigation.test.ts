import { describe, expect, it } from "vitest";

import { generateGardenLayout } from "../src/generator/layout";
import { mockGardenSnapshot } from "../src/mock/garden";
import {
  describeFocus,
  focusFromString,
  focusTrail,
  focusToString,
  GARDEN_FOCUS,
  moveSibling,
  sanitizeFocus,
  zoomIn,
  zoomOut,
} from "../src/model/navigation";
import type { GardenFocus } from "../src/model/types";

const snapshot = mockGardenSnapshot();
const layout = generateGardenLayout(snapshot);
const firstGrove = layout.groves[0]!;
const plantId = firstGrove.conceptIds[2]!;

describe("navigation", () => {
  it("zooms out one level at a time", () => {
    const part: GardenFocus = { level: "part", conceptId: plantId, part: "stem" };
    expect(zoomOut(part, layout)).toEqual({ level: "plant", conceptId: plantId });
    expect(zoomOut({ level: "plant", conceptId: plantId }, layout)).toEqual({
      level: "grove",
      groveId: firstGrove.id,
    });
    expect(zoomOut({ level: "grove", groveId: firstGrove.id }, layout)).toEqual(GARDEN_FOCUS);
    expect(zoomOut(GARDEN_FOCUS, layout)).toEqual(GARDEN_FOCUS);
  });

  it("zooms in to the first child", () => {
    let focus: GardenFocus = GARDEN_FOCUS;
    focus = zoomIn(focus, layout);
    expect(focus).toEqual({ level: "grove", groveId: firstGrove.id });
    focus = zoomIn(focus, layout);
    expect(focus).toEqual({ level: "plant", conceptId: firstGrove.conceptIds[0] });
    focus = zoomIn(focus, layout);
    expect(focus).toMatchObject({ level: "part", part: "roots" });
    expect(zoomIn(focus, layout)).toEqual(focus);
  });

  it("moves between siblings and wraps", () => {
    const lastGrove = layout.groves.at(-1)!;
    expect(moveSibling({ level: "grove", groveId: firstGrove.id }, layout, -1)).toEqual({
      level: "grove",
      groveId: lastGrove.id,
    });
    expect(moveSibling({ level: "plant", conceptId: plantId }, layout, 1)).toEqual({
      level: "plant",
      conceptId: firstGrove.conceptIds[3],
    });
    expect(moveSibling({ level: "part", conceptId: plantId, part: "blossoms" }, layout, 1)).toEqual(
      { level: "part", conceptId: plantId, part: "roots" },
    );
    expect(moveSibling(GARDEN_FOCUS, layout, 1)).toEqual(GARDEN_FOCUS);
  });

  it("round-trips focus through strings", () => {
    const foci: GardenFocus[] = [
      GARDEN_FOCUS,
      { level: "grove", groveId: "dsa" },
      { level: "plant", conceptId: "dsa.graphs" },
      { level: "part", conceptId: "dsa.graphs", part: "blossoms" },
    ];
    for (const focus of foci) expect(focusFromString(focusToString(focus))).toEqual(focus);
    expect(focusFromString("part:dsa.graphs:leaves")).toEqual(GARDEN_FOCUS);
    expect(focusFromString(null)).toEqual(GARDEN_FOCUS);
  });

  it("drops focus on things not in the garden", () => {
    expect(sanitizeFocus({ level: "plant", conceptId: "nope" }, layout)).toEqual(GARDEN_FOCUS);
    expect(sanitizeFocus({ level: "grove", groveId: firstGrove.id }, layout).level).toBe("grove");
  });

  it("builds breadcrumbs and descriptions", () => {
    const trail = focusTrail({ level: "part", conceptId: plantId, part: "roots" }, layout);
    expect(trail.map((f) => f.level)).toEqual(["garden", "grove", "plant", "part"]);
    expect(describeFocus(GARDEN_FOCUS, snapshot)).toContain(`${snapshot.plants.length} concepts`);
    expect(describeFocus({ level: "part", conceptId: plantId, part: "roots" }, snapshot)).toContain(
      "independent",
    );
  });
});
