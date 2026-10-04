import type { LiveGrowthEvent } from "@sg/contracts";
import { describe, expect, it } from "vitest";

import { createCueSelector } from "./cues";

const event = (over: Partial<LiveGrowthEvent> = {}): LiveGrowthEvent => ({
  id: "e1",
  kind: "provisional",
  sessionId: "s1",
  conceptId: "dsa.binary_search",
  questionId: null,
  dimension: "knowledge",
  part: "roots",
  assisted: false,
  outcome: "demonstrated",
  quote: "q",
  reason: "r",
  occurredAt: "2026-10-04T00:00:00Z",
  note: "",
  judge: "test",
  ...over,
});

describe("createCueSelector", () => {
  it("chimes growth for independent growth and bloom for blossoms", () => {
    const s = createCueSelector();
    expect(s.select(event())?.type).toBe("growth");
    expect(s.select(event({ part: "blossoms" }))?.type).toBe("bloom");
  });

  it("is silent for assisted, retracted, noted and part-less events", () => {
    const s = createCueSelector();
    expect(s.select(event({ assisted: true }))).toBeNull();
    expect(s.select(event({ kind: "retracted" }))).toBeNull();
    expect(s.select(event({ kind: "noted" }))).toBeNull();
    expect(s.select(event({ part: null }))).toBeNull();
  });

  it("does not repeat the cue when a confirmation follows its provisional glow", () => {
    const s = createCueSelector();
    expect(s.select(event())).not.toBeNull();
    expect(s.select(event({ id: "e2", kind: "confirmed" }))).toBeNull();
    s.reset();
    expect(s.select(event({ id: "e3", kind: "confirmed" }))).not.toBeNull();
  });
});
