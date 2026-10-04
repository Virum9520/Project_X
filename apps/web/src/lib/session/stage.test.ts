import type { LiveGrowthEvent } from "@sg/contracts";
import { describe, expect, it, vi } from "vitest";

import { AlignmentClock } from "./alignment-clock";
import { activePulses, parseGrowthEvent, pulses } from "./growth-sse";
import { parseQuestionId } from "./question-id";
import {
  INITIAL_STAGE,
  MAX_TICKER,
  PULSE_MS,
  createStageTools,
  pulseConceptIds,
  stageReducer,
  type StageAction,
  type StageState,
} from "./stage";

function harness(known = ["dsa.binary_search"]) {
  let state: StageState = INITIAL_STAGE;
  const dispatch = (a: StageAction) => {
    state = stageReducer(state, a);
  };
  const focusPlant = vi.fn(() => "Focused.");
  const tools = createStageTools({
    dispatch,
    now: () => 1000,
    hasConcept: (k) => known.includes(k),
    focusPlant,
  });
  return { tools, focusPlant, get: () => state };
}

describe("show_question_card", () => {
  it("shows a card and enters Teach-back for a teach_back question", () => {
    const h = harness();
    const msg = h.tools.show_question_card({
      question_id: "teach_back:dsa.binary_search:0",
      title: "Teach me",
      body: "Explain binary search to me.",
    });
    expect(msg).toContain("Teach-back");
    expect(h.get().teachBack).toBe(true);
    expect(h.get().teachBackStartedAt).toBe(1000);
    expect(h.get().card?.conceptId).toBe("dsa.binary_search");
  });

  it("leaves Teach-back when a normal question follows", () => {
    const h = harness();
    h.tools.show_question_card({
      question_id: "teach_back:dsa.binary_search:0",
      title: "t",
      body: "b",
    });
    h.tools.show_question_card({
      question_id: "concept_check:dsa.binary_search:1",
      title: "t",
      body: "b",
    });
    expect(h.get().teachBack).toBe(false);
    expect(h.get().teachBackStartedAt).toBeNull();
  });

  it("keeps the role for an unparseable id and rejects empty input", () => {
    const h = harness();
    h.tools.show_question_card({
      question_id: "teach_back:dsa.binary_search:0",
      title: "t",
      body: "b",
    });
    h.tools.show_question_card({ question_id: "weird", title: "", body: "b" });
    expect(h.get().teachBack).toBe(true);
    expect(h.get().card?.title).toBe("Question");
    expect(h.tools.show_question_card({ question_id: "", body: "" })).toMatch(/required/);
  });

  it("flattens and bounds LLM text", () => {
    const h = harness();
    h.tools.show_question_card({ question_id: "q", title: "a\n\nb", body: "x".repeat(2000) });
    expect(h.get().card?.title).toBe("a b");
    expect(h.get().card?.body.length).toBe(600);
  });
});

describe("highlight_plant", () => {
  it("highlights a known concept for a limited time", () => {
    const h = harness();
    expect(h.tools.highlight_plant({ concept_id: "dsa.binary_search", part: "roots" })).toMatch(
      /Highlighted/,
    );
    const s = h.get();
    expect(s.highlight).toEqual({
      conceptId: "dsa.binary_search",
      part: "roots",
      until: 1000 + PULSE_MS,
    });
    expect([...pulseConceptIds(s, new Set(["x.y"]), 2000)].sort()).toEqual([
      "dsa.binary_search",
      "x.y",
    ]);
    expect(pulseConceptIds(s, new Set(), 1000 + PULSE_MS + 1).size).toBe(0);
  });

  it("returns correctable errors", () => {
    const h = harness();
    expect(h.tools.highlight_plant({ concept_id: "nope" })).toMatch(/look like/);
    expect(h.tools.highlight_plant({ concept_id: "dsa.unknown" })).toMatch(/Unknown concept/);
    expect(
      h.tools.highlight_plant({ concept_id: "dsa.binary_search", part: "leaf" as never }),
    ).toMatch(/part must/);
    expect(h.get().highlight).toBeNull();
  });
});

describe("open_editor, show_diagram, focus_plant", () => {
  it("validates the language and problem id", () => {
    const h = harness();
    expect(h.tools.open_editor({ problem_id: "p1", language: "cobol" as never })).toMatch(
      /language/,
    );
    expect(h.tools.open_editor({ problem_id: "p1", language: "python" })).toBe("Editor opened.");
    expect(h.get().editor).toEqual({ problem_id: "p1", language: "python" });
  });

  it("validates the diagram id", () => {
    const h = harness();
    expect(h.tools.show_diagram({ diagram_id: "<script>" })).toMatch(/malformed/);
    expect(h.tools.show_diagram({ diagram_id: "bs_trace", caption: "Halving" })).toMatch(
      /on screen/,
    );
    expect(h.get().diagram).toEqual({ id: "bs_trace", caption: "Halving" });
  });

  it("delegates focus_plant to the garden handler", () => {
    const h = harness();
    expect(h.tools.focus_plant({ level: "plant", target_id: "dsa.binary_search" })).toBe(
      "Focused.",
    );
    expect(h.focusPlant).toHaveBeenCalledWith({ level: "plant", target_id: "dsa.binary_search" });
  });
});

const event = (over: Partial<LiveGrowthEvent> = {}): LiveGrowthEvent => ({
  id: "e1",
  kind: "provisional",
  sessionId: "s",
  conceptId: "dsa.binary_search",
  questionId: null,
  dimension: "explanation",
  part: "roots",
  outcome: "demonstrated",
  assisted: false,
  quote: "q",
  note: "",
  judge: "j",
  reason: "",
  occurredAt: "2026-10-04T10:00:00Z",
  ...over,
});

describe("evidence ticker", () => {
  it("adds newest first, bounded", () => {
    let s = INITIAL_STAGE;
    for (let i = 0; i < MAX_TICKER + 3; i++)
      s = stageReducer(s, { type: "growth", event: event({ id: `e${i}`, conceptId: `a.b${i}` }) });
    expect(s.ticker).toHaveLength(MAX_TICKER);
    expect(s.ticker[0].id).toBe(`e${MAX_TICKER + 2}`);
  });

  it("confirmation replaces the provisional entry for the same plant part", () => {
    let s = stageReducer(INITIAL_STAGE, { type: "growth", event: event() });
    s = stageReducer(s, { type: "growth", event: event({ id: "e2", kind: "confirmed" }) });
    expect(s.ticker.map((t) => t.kind)).toEqual(["confirmed"]);
  });

  it("a retraction keeps its reason", () => {
    let s = stageReducer(INITIAL_STAGE, { type: "growth", event: event() });
    s = stageReducer(s, {
      type: "growth",
      event: event({ id: "e3", kind: "retracted", reason: "The answer leaned on a hint." }),
    });
    expect(s.ticker[0]).toMatchObject({
      kind: "retracted",
      reason: "The answer leaned on a hint.",
    });
    expect(s.ticker).toHaveLength(1);
  });
});

describe("growth stream parsing", () => {
  it("accepts a camelCase payload and drops bad frames", () => {
    const good = parseGrowthEvent(JSON.stringify({ ...event(), extra: 1 }));
    expect(good?.conceptId).toBe("dsa.binary_search");
    expect(parseGrowthEvent("not json")).toBeNull();
    expect(parseGrowthEvent(JSON.stringify({ id: "x" }))).toBeNull();
    expect(parseGrowthEvent(JSON.stringify({ ...event(), kind: "wow" }))).toBeNull();
  });

  it("normalises unknown parts and only pulses on real growth", () => {
    expect(parseGrowthEvent(JSON.stringify({ ...event(), part: "leaf" }))?.part).toBeNull();
    expect(pulses(event())).toBe(true);
    expect(pulses(event({ kind: "noted" }))).toBe(false);
  });

  it("expires pulses", () => {
    const last = new Map([
      ["a.b", 100],
      ["c.d", 5000],
    ]);
    expect([...activePulses(last, 6000, 2000)]).toEqual(["c.d"]);
  });
});

describe("alignment clock", () => {
  it("offsets chunks from the first chunk of an utterance and resets", () => {
    let t = 1000;
    const clock = new AlignmentClock(() => t);
    expect(clock.offsetForChunk()).toBe(0);
    t = 1450;
    expect(clock.offsetForChunk()).toBe(450);
    clock.reset();
    t = 9000;
    expect(clock.offsetForChunk()).toBe(0);
  });
});

describe("question ids", () => {
  it("parses ids from fetch_question", () => {
    expect(parseQuestionId("cross_question:dsa.bfs:2")).toEqual({
      kind: "cross_question",
      conceptKey: "dsa.bfs",
      variant: 2,
    });
    expect(parseQuestionId("bogus:dsa.bfs:2")).toBeNull();
    expect(parseQuestionId("teach_back:dsa.bfs:x")).toBeNull();
  });
});
