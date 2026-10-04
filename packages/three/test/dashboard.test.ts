import type { EvidenceItem, PlantState } from "@sg/contracts";
import { describe, expect, it } from "vitest";

import { evidenceCardsFor, plantGrowth, snapshotFromPlants } from "../src";

const nulls = { explanation: null, application: null, transfer: null, retention: null };

function plant(key: string, over: Partial<PlantState> = {}): PlantState {
  return {
    meta: { key, title: key.toUpperCase(), grove: "dsa", difficulty: 2 },
    stage: "independent",
    independent: { ...nulls, explanation: 0.8 },
    assisted: { ...nulls, explanation: 0.9, application: 0.4 },
    lastEvidenceAt: "2026-10-01T10:00:00.000Z",
    nextReviewAt: "2026-10-08T10:00:00.000Z",
    wilting: false,
    matched: true,
    evidenceCount: { independent: 2, assisted: 1 },
    ...over,
  };
}

const base = {
  groves: [{ id: "dsa" as const, title: "Data structures" }],
  asOf: "2026-10-04T00:00:00.000Z",
  revision: 4,
  ruleVersion: "rules@1",
};

describe("snapshotFromPlants", () => {
  it("keeps assisted scores separate and defaults missing scores to zero", () => {
    const snap = snapshotFromPlants({ ...base, plants: [plant("dsa.bfs")] });
    const p = snap.plants[0]!;
    expect(p.conceptId).toBe("dsa.bfs");
    expect(p.dimensions.explanation).toEqual({ independent: 0.8, assisted: 0.9 });
    expect(p.dimensions.application).toEqual({ independent: 0, assisted: 0.4 });
    expect(p.dimensions.retention).toEqual({ independent: 0, assisted: 0 });
    expect(p.evidenceCount).toBe(3);
    expect(snap.groves).toEqual([{ id: "dsa", label: "Data structures" }]);
    expect(snap.revision).toBe(4);
  });

  it("maps wilting over the stage and keeps every plant, filtered or not", () => {
    const snap = snapshotFromPlants({
      ...base,
      plants: [
        plant("a", { wilting: true, stage: "retained" }),
        plant("b", { stage: "unassessed", matched: false }),
      ],
    });
    expect(snap.plants.map((p) => p.status)).toEqual(["wilting", "unassessed"]);
  });

  it("drops prerequisite edges that point at unknown plants", () => {
    const snap = snapshotFromPlants({
      ...base,
      plants: [plant("a"), plant("b")],
      prerequisites: [
        { from: "a", to: "b" },
        { from: "a", to: "zzz" },
      ],
    });
    expect(snap.prerequisites).toEqual([{ from: "a", to: "b" }]);
  });

  it("grows the scene the same way as the mock: assisted shows as ghost growth", () => {
    const snap = snapshotFromPlants({
      ...base,
      plants: [plant("a", { independent: nulls, stage: "assisted" })],
    });
    const growth = plantGrowth(snap.plants[0]!);
    expect(growth.parts.roots.solid).toBe(0);
    expect(growth.parts.roots.confirmed).toBeGreaterThan(0);
  });
});

describe("evidenceCardsFor", () => {
  const item = (id: string, over: Partial<EvidenceItem> = {}): EvidenceItem => ({
    id,
    plantKey: "dsa.bfs",
    dimension: "explanation",
    kind: "independent",
    character: "drona",
    sessionId: "s1",
    occurredAt: "2026-10-01T10:00:00.000Z",
    quote: "level by level",
    source: "transcript",
    rationale: "ok",
    confidence: 0.8,
    weight: 0.9,
    rubricVersion: "rubric@1",
    status: "confirmed",
    ...over,
  });

  it("filters by plant and part, newest first, and flags assisted evidence", () => {
    const cards = evidenceCardsFor(
      [
        item("old", { occurredAt: "2026-09-01T00:00:00.000Z" }),
        item("new", { kind: "assisted", source: "tests" }),
        item("other-plant", { plantKey: "dsa.dfs" }),
        item("other-part", { dimension: "application" }),
      ],
      "dsa.bfs",
      "roots",
    );
    expect(cards.map((c) => c.id)).toEqual(["new", "old"]);
    expect(cards[0]).toMatchObject({ independent: false, kind: "test", uncertainty: 0.2 });
    expect(cards[1]).toMatchObject({ independent: true, kind: "transcript" });
  });

  it("caps the number of cards", () => {
    const many = Array.from({ length: 10 }, (_, i) => item(`e${i}`));
    expect(evidenceCardsFor(many, "dsa.bfs", "roots", 3)).toHaveLength(3);
  });
});
