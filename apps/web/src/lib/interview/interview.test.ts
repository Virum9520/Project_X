import { describe, expect, it } from "vitest";

import {
  DeliveryAccumulator,
  MIN_SAMPLES,
  PaceTracker,
  classifyFrame,
  sampleFromLandmarks,
} from "./delivery";
import {
  INITIAL_DIRECTOR,
  MIN_DWELL_MS,
  directorReducer,
  shotWeight,
  type DirectorState,
} from "./director";
import { lastSpeaker, parseVoiceTags, plainText, speakerOfMessage } from "./speaker";

describe("voice tags", () => {
  it("splits Vidura and Arjuna lines and strips the tags", () => {
    const raw = "Thanks. Arjuna, over to you. <Arjuna>Thanks, Vidura. Here is a problem.</Arjuna>";
    expect(parseVoiceTags(raw)).toEqual([
      { speaker: "vidura", text: "Thanks. Arjuna, over to you." },
      { speaker: "arjuna", text: "Thanks, Vidura. Here is a problem." },
    ]);
    expect(plainText(raw)).not.toContain("<");
    expect(lastSpeaker(raw)).toBe("arjuna");
  });

  it("treats an unclosed tag (streaming) as the open speaker", () => {
    expect(lastSpeaker("<Arjuna>Let's look at")).toBe("arjuna");
  });

  it("returns to Vidura after the closing tag and drops unknown tags", () => {
    expect(lastSpeaker("<Arjuna>Hi.</Arjuna> Back to me <b>now</b>.")).toBe("vidura");
    expect(plainText("a <b>b</b>")).toBe("a b");
  });

  it("is case-insensitive and tolerates spaces", () => {
    expect(lastSpeaker("< arjuna >ok</ arjuna >")).toBe("arjuna");
    expect(lastSpeaker("< arjuna >ok</ arjuna > thanks")).toBe("vidura");
    expect(lastSpeaker("<ARJUNA>ok")).toBe("arjuna");
  });

  it("prefers an explicit voice label, then tags, then the fallback", () => {
    expect(speakerOfMessage({ voice_label: "Arjuna", message: "hi" })).toBe("arjuna");
    expect(speakerOfMessage({ message: "<Arjuna>hi</Arjuna><Arjuna>x" })).toBe("arjuna");
    expect(speakerOfMessage(null, "arjuna")).toBe("arjuna");
    expect(speakerOfMessage({ voice_label: "Mallory", message: "hello" })).toBe("vidura");
  });
});

describe("camera director", () => {
  const at = (s: DirectorState, ms: number, type: "arjuna" | "vidura" | "wide" | "tick") =>
    type === "tick"
      ? directorReducer(s, { type: "tick", now: ms })
      : type === "wide"
        ? directorReducer(s, { type: "candidate_turn", now: ms })
        : directorReducer(s, { type: "agent_speaking", speaker: type, now: ms });

  it("cuts to the speaker, then wide for the candidate", () => {
    let s = at(INITIAL_DIRECTOR, 5000, "vidura");
    expect(s.shot).toBe("vidura");
    s = at(s, 5000 + MIN_DWELL_MS, "wide");
    expect(s.shot).toBe("wide");
  });

  it("holds a too-early cut and applies it on tick", () => {
    let s = at(INITIAL_DIRECTOR, 5000, "vidura");
    s = at(s, 5300, "arjuna");
    expect(s.shot).toBe("vidura");
    expect(s.pending).toBe("arjuna");
    s = at(s, 5000 + MIN_DWELL_MS, "tick");
    expect(s.shot).toBe("arjuna");
    expect(s.pending).toBeNull();
  });

  it("drops a pending cut when the shot comes back", () => {
    let s = at(INITIAL_DIRECTOR, 5000, "vidura");
    s = at(s, 5200, "arjuna");
    s = at(s, 5300, "vidura");
    expect(s.pending).toBeNull();
  });

  it("weights the speaker's column up", () => {
    expect(shotWeight("wide", "arjuna")).toBe(1);
    expect(shotWeight("arjuna", "arjuna")).toBeGreaterThan(shotWeight("arjuna", "vidura"));
  });
});

describe("delivery observations", () => {
  const face = (over = {}) => ({
    box: { x: 0.3, y: 0.25, w: 0.35, h: 0.45 },
    yaw: 0.05,
    ...over,
  });

  it("classifies framing and facing", () => {
    expect(classifyFrame(face())).toEqual({ framed: true, facing: true });
    expect(classifyFrame(face({ yaw: 0.6 }))).toEqual({ framed: true, facing: false });
    expect(classifyFrame({ box: null, yaw: null })).toEqual({ framed: false, facing: false });
    // Cropped at the edge, or too small.
    expect(classifyFrame(face({ box: { x: 0, y: 0.25, w: 0.35, h: 0.45 } })).framed).toBe(false);
    expect(classifyFrame(face({ box: { x: 0.4, y: 0.4, w: 0.1, h: 0.1 } })).framed).toBe(false);
  });

  it("summarises only with enough samples and rounds to the API contract", () => {
    const acc = new DeliveryAccumulator();
    for (let i = 0; i < MIN_SAMPLES - 1; i++) acc.add(face());
    expect(acc.summary(60, 120)).toBeNull();
    acc.add(face({ yaw: 0.9 }));
    const s = acc.summary(540, 138.456);
    expect(s).toMatchObject({ consent: true, samples: MIN_SAMPLES, framing_ratio: 1 });
    expect(s?.gaze_ratio).toBeCloseTo(0.9, 5);
    expect(s?.pace_wpm).toBe(138.5);
    // Nothing but the six contract fields.
    expect(Object.keys(s ?? {}).sort()).toEqual(
      ["consent", "duration_s", "framing_ratio", "gaze_ratio", "pace_wpm", "samples"].sort(),
    );
  });

  it("reads landmarks into a box and a yaw proxy", () => {
    const pts = Array.from({ length: 468 }, () => ({ x: 0.5, y: 0.5 }));
    pts[10] = { x: 0.5, y: 0.2 };
    pts[152] = { x: 0.5, y: 0.7 };
    pts[234] = { x: 0.3, y: 0.45 };
    pts[454] = { x: 0.7, y: 0.45 };
    pts[1] = { x: 0.5, y: 0.5 };
    const s = sampleFromLandmarks(pts);
    expect(s.yaw).toBeCloseTo(0);
    expect(s.box?.h).toBeCloseTo(0.5);
    expect(sampleFromLandmarks([])).toEqual({ box: null, yaw: null });
  });

  it("measures pace from the listening window and ignores pathological ones", () => {
    const pace = new PaceTracker();
    pace.markListening(0);
    pace.onLearnerMessage(Array(60).fill("word").join(" "), 30_000);
    expect(pace.wpm).toBeCloseTo(120);
    pace.markListening(40_000);
    pace.onLearnerMessage("ok", 40_500); // too short a window
    pace.markListening(50_000);
    pace.onLearnerMessage("long pause", 400_000); // over three minutes
    expect(pace.wpm).toBeCloseTo(120);
    expect(new PaceTracker().wpm).toBeNull();
  });
});
