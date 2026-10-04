import { describe, expect, it } from "vitest";

import {
  MUSIC_CEILING,
  computeMix,
  dayPartFor,
  isDecorative,
  moodFor,
  panFor,
  seasonFor,
  sfxFor,
  stemId,
} from "../src/mix";
import { parsePrefs, readPrefs, writePrefs } from "../src/prefs";
import { segmentAt } from "../src/recap";

const plants = (stages: string[], wilting: number[] = []) =>
  stages.map((stage, i) => ({ stage, wilting: wilting.includes(i) }));

describe("moodFor", () => {
  it("is seedling until enough plants have evidence", () => {
    expect(moodFor({ plants: [] })).toBe("seedling");
    expect(moodFor({ plants: plants(["independent", "independent", "unassessed"]) })).toBe(
      "seedling",
    );
  });
  it("thrives when most assessed plants are grown independently", () => {
    expect(moodFor({ plants: plants(["independent", "transfer", "retained", "sprouting"]) })).toBe(
      "thriving",
    );
  });
  it("wilts when a third of assessed plants are overdue, whatever else is going on", () => {
    expect(
      moodFor({ plants: plants(["independent", "independent", "retained", "sprouting"], [0, 3]) }),
    ).toBe("wilting");
  });
  it("assisted-only growth does not count as thriving", () => {
    expect(moodFor({ plants: plants(["assisted", "assisted", "assisted", "assisted"]) })).toBe(
      "seedling",
    );
  });
  it("blooms while celebrating", () => {
    expect(moodFor({ plants: [], celebrating: true })).toBe("blooming");
  });
});

describe("time and season", () => {
  it("maps hours to day parts, wrapping around midnight", () => {
    expect([6, 12, 19, 23, 2, 26].map(dayPartFor)).toEqual([
      "dawn",
      "day",
      "dusk",
      "night",
      "night",
      "night",
    ]);
  });
  it("maps months to seasons", () => {
    expect(seasonFor(new Date(2026, 0, 5))).toBe("winter");
    expect(seasonFor(new Date(2026, 3, 5))).toBe("spring");
    expect(seasonFor(new Date(2026, 6, 5))).toBe("summer");
    expect(seasonFor(new Date(2026, 9, 5))).toBe("autumn");
    expect(seasonFor(new Date(2026, 11, 5))).toBe("winter");
  });
});

describe("computeMix", () => {
  const base = {
    mood: "thriving",
    season: "autumn",
    dayPart: "day",
    muted: false,
    volume: 1,
    reducedMotion: false,
  } as const;
  it("selects exactly one stem", () => {
    expect(computeMix(base).stems).toEqual({ [stemId("thriving", "autumn")]: 1 });
    expect(stemId("thriving", "autumn")).toBe("music.thriving.autumn");
  });
  it("is silent when muted and never louder than the ceiling", () => {
    expect(computeMix({ ...base, muted: true }).master).toBe(0);
    expect(computeMix(base).master).toBeLessThanOrEqual(MUSIC_CEILING);
    expect(computeMix({ ...base, volume: 9 }).master).toBeLessThanOrEqual(MUSIC_CEILING);
    expect(computeMix({ ...base, volume: Number.NaN }).master).toBe(0);
  });
  it("is quieter and darker at night", () => {
    const night = computeMix({ ...base, dayPart: "night" });
    const day = computeMix(base);
    expect(night.master).toBeLessThan(day.master);
    expect(night.cutoffHz).toBeLessThan(day.cutoffHz);
  });
  it("reduced motion shortens crossfades, drops decorative sfx and spatial panning", () => {
    const calm = computeMix({ ...base, reducedMotion: true });
    expect(calm.crossfadeSeconds).toBeLessThan(computeMix(base).crossfadeSeconds);
    expect(calm.decorativeSfx).toBe(false);
    expect(calm.spatial).toBe(false);
    expect(calm.master).toBeLessThan(computeMix(base).master);
    expect(computeMix(base).decorativeSfx).toBe(true);
  });
});

describe("events", () => {
  it("maps events to effect names", () => {
    expect(sfxFor({ type: "bloom" })).toBe("bloom");
    expect(sfxFor({ type: "ui", action: "open" })).toBe("ui_open");
    expect(sfxFor({ type: "recap_start" })).toBe("recap_start");
  });
  it("only growth, bloom and wilt are decorative", () => {
    expect(isDecorative({ type: "growth" })).toBe(true);
    expect(isDecorative({ type: "ring" })).toBe(false);
    expect(isDecorative({ type: "ui", action: "click" })).toBe(false);
  });
  it("pans within the stereo field", () => {
    expect(panFor(0, 10)).toBe(0);
    expect(panFor(-10, 10)).toBeCloseTo(-0.8);
    expect(panFor(99, 10)).toBeCloseTo(0.8);
    expect(panFor(5, 0)).toBe(0);
  });
});

describe("prefs", () => {
  it("defaults to muted and survives bad data", () => {
    expect(parsePrefs(null)).toEqual({ muted: true, volume: 0.7 });
    expect(parsePrefs("{nope")).toEqual({ muted: true, volume: 0.7 });
    expect(parsePrefs('{"muted":false,"volume":4}')).toEqual({ muted: false, volume: 1 });
    expect(parsePrefs('"x"')).toEqual({ muted: true, volume: 0.7 });
  });
  it("tolerates blocked storage", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect(readPrefs(blocked)).toEqual({ muted: true, volume: 0.7 });
    expect(() => writePrefs({ muted: false, volume: 0.5 }, blocked)).not.toThrow();
  });
  it("round-trips", () => {
    const data = new Map<string, string>();
    const storage = {
      getItem: (k: string) => data.get(k) ?? null,
      setItem: (k: string, v: string) => void data.set(k, v),
    };
    writePrefs({ muted: false, volume: 0.25 }, storage);
    expect(readPrefs(storage)).toEqual({ muted: false, volume: 0.25 });
  });
});

describe("segmentAt", () => {
  const segs = [
    { startMs: 0, endMs: 1000 },
    { startMs: 1000, endMs: 2500 },
    { startMs: 2500, endMs: 4000 },
  ];
  it("finds the segment being spoken", () => {
    expect(segmentAt(segs, 0)).toBe(segs[0]);
    expect(segmentAt(segs, 1000)).toBe(segs[1]);
    expect(segmentAt(segs, 3999)).toBe(segs[2]);
    expect(segmentAt(segs, 99999)).toBe(segs[2]);
    expect(segmentAt([], 5)).toBeNull();
  });
});
