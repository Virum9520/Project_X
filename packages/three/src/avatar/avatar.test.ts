import { describe, expect, it } from "vitest";
import { alignmentToSegments, fromTtsTimestamps } from "./alignment";
import { createIdleAnimator } from "./idle";
import { LipSyncDriver } from "./lipsync-driver";
import { mockAlignment } from "./mock";
import { VisemeTimeline } from "./timeline";

describe("alignmentToSegments", () => {
  it("maps vowels to VRM visemes with timings", () => {
    const segs = alignmentToSegments(mockAlignment("a e i o u", 100));
    expect(segs.map((s) => s.viseme)).toEqual(["aa", "ee", "ih", "oh", "ou"]);
    expect(segs[0]).toMatchObject({ startMs: 0, endMs: 100 });
    expect(segs[1]).toMatchObject({ startMs: 200, endMs: 300 });
  });

  it("merges digraphs into one segment spanning both characters", () => {
    const [seg, ...rest] = alignmentToSegments(mockAlignment("oo", 50));
    expect(rest).toHaveLength(0);
    expect(seg).toMatchObject({ viseme: "ou", startMs: 0, endMs: 100 });
  });

  it("closes the mouth for bilabials, spaces and punctuation", () => {
    expect(alignmentToSegments(mockAlignment("mp b, .!?"))).toEqual([]);
  });

  it("gives consonants weaker shapes than vowels", () => {
    const [cons, vowel] = alignmentToSegments(mockAlignment("sa"));
    expect(cons?.weight).toBeLessThan(vowel?.weight ?? 0);
  });

  it("folds case and diacritics", () => {
    const segs = alignmentToSegments(mockAlignment("É"));
    expect(segs.map((s) => s.viseme)).toEqual(["ee"]);
  });

  it("applies the chunk offset and tolerates ragged arrays", () => {
    const segs = alignmentToSegments(
      { chars: ["a", "o"], charStartTimesMs: [0], charDurationsMs: [10] },
      500,
    );
    expect(segs).toHaveLength(1);
    expect(segs[0]?.startMs).toBe(500);
  });

  it("converts REST with-timestamps alignment to ms", () => {
    const a = fromTtsTimestamps({
      characters: ["h", "i"],
      character_start_times_seconds: [0, 0.1],
      character_end_times_seconds: [0.1, 0.25],
    });
    expect(a.charStartTimesMs).toEqual([0, 100]);
    expect(a.charDurationsMs[1]).toBeCloseTo(150);
  });
});

describe("VisemeTimeline", () => {
  const timeline = () => {
    const t = new VisemeTimeline({ attackMs: 40, releaseMs: 60 });
    t.append(mockAlignment("a e", 100)); // aa 0-100, ee 200-300
    return t;
  };

  it("is silent when empty and before/after the speech", () => {
    const t = timeline();
    expect(t.isActive(-500)).toBe(false);
    expect(t.isActive(1000)).toBe(false);
    expect(new VisemeTimeline().sample(0)).toEqual({ aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 });
  });

  it("holds the peak weight during a segment", () => {
    const w = timeline().sample(50);
    expect(w.aa).toBeCloseTo(0.9);
    expect(w.ee).toBe(0);
  });

  it("ramps in before and out after a segment", () => {
    const t = timeline();
    const pre = t.sample(-20).aa;
    expect(pre).toBeGreaterThan(0);
    expect(pre).toBeLessThan(0.9);
    const post = t.sample(130).aa;
    expect(post).toBeGreaterThan(0);
    expect(post).toBeLessThan(0.9);
    expect(t.sample(161).aa).toBe(0);
  });

  it("appends streamed chunks at an audio offset and stays sorted", () => {
    const t = new VisemeTimeline();
    t.append(mockAlignment("o", 100), 1000);
    t.append(mockAlignment("a", 100), 0);
    expect(t.sample(50).aa).toBeGreaterThan(0.8);
    expect(t.sample(1050).oh).toBeGreaterThan(0.8);
    expect(t.endMs).toBe(1100);
  });

  it("clear drops everything", () => {
    const t = timeline();
    t.clear();
    expect(t.length).toBe(0);
    expect(t.isActive(50)).toBe(false);
  });
});

describe("createIdleAnimator", () => {
  it("is deterministic for a seed", () => {
    const run = (seed: number) => {
      const a = createIdleAnimator(seed);
      return Array.from({ length: 600 }, () => a.update(1 / 60));
    };
    expect(run(7)).toEqual(run(7));
  });

  it("blinks within a few seconds and stays in range", () => {
    const a = createIdleAnimator(3);
    let maxBlink = 0;
    for (let i = 0; i < 60 * 8; i++) {
      const s = a.update(1 / 60);
      maxBlink = Math.max(maxBlink, s.blink);
      expect(s.blink).toBeGreaterThanOrEqual(0);
      expect(s.blink).toBeLessThanOrEqual(1);
      expect(Math.abs(s.lookX)).toBeLessThanOrEqual(1);
    }
    expect(maxBlink).toBeGreaterThan(0.9);
  });
});

describe("LipSyncDriver", () => {
  it("drives the mouth from alignment on the injected clock", () => {
    let now = 1000;
    const d = new LipSyncDriver({ now: () => now, smoothing: 1000 });
    d.pushAlignment(mockAlignment("a", 200)); // starts playback at 1000
    now = 1100;
    const f = d.frame(now, 0.1);
    expect(f.speaking).toBe(true);
    expect(f.mouth.aa).toBeGreaterThan(0.8);
    const after = d.frame(2000, 0.1);
    expect(after.speaking).toBe(false);
    expect(after.mouth.aa).toBeLessThan(0.01);
  });

  it("falls back to the output level when no alignment is active", () => {
    const d = new LipSyncDriver({ smoothing: 1000 });
    d.setLevel(1);
    const f = d.frame(0, 0.1);
    expect(f.speaking).toBe(true);
    expect(f.mouth.aa).toBeGreaterThan(0.7);
    d.setLevel(0);
    expect(d.frame(0, 0.1).speaking).toBe(false);
  });

  it("reset clears queued alignment", () => {
    const d = new LipSyncDriver({ now: () => 0, smoothing: 1000 });
    d.pushAlignment(mockAlignment("a", 500));
    d.reset();
    expect(d.frame(100, 0.1).speaking).toBe(false);
  });

  it("smooths mouth movement rather than snapping", () => {
    const d = new LipSyncDriver({ now: () => 0, smoothing: 10 });
    d.pushAlignment(mockAlignment("a", 500));
    const f = d.frame(100, 1 / 60);
    expect(f.mouth.aa).toBeGreaterThan(0);
    expect(f.mouth.aa).toBeLessThan(0.5);
  });
});
