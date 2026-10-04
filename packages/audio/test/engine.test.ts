import { describe, expect, it, vi } from "vitest";

import { SoundscapeEngine, type SoundAsset } from "../src/engine";

class FakeParam {
  value = 0;
  targets: number[] = [];
  ramps: number[] = [];
  setValueAtTime(v: number) {
    this.value = v;
  }
  setTargetAtTime(v: number) {
    this.targets.push(v);
    this.value = v;
  }
  linearRampToValueAtTime(v: number) {
    this.ramps.push(v);
  }
  cancelScheduledValues() {}
}
class FakeNode {
  connected: unknown[] = [];
  connect(n: unknown) {
    this.connected.push(n);
    return n;
  }
  disconnect() {}
}
class FakeGain extends FakeNode {
  gain = new FakeParam();
}
class FakeFilter extends FakeNode {
  type = "";
  frequency = new FakeParam();
}
class FakePanner extends FakeNode {
  pan = new FakeParam();
}
class FakeSource extends FakeNode {
  buffer: unknown = null;
  loop = false;
  started = 0;
  stopped = 0;
  onended: (() => void) | null = null;
  start() {
    this.started += 1;
  }
  stop() {
    this.stopped += 1;
  }
}

function makeContext(state: "running" | "suspended" = "running") {
  const sources: FakeSource[] = [];
  const panners: FakePanner[] = [];
  const gains: FakeGain[] = [];
  const ctx = {
    state,
    currentTime: 0,
    destination: new FakeNode(),
    createGain: () => {
      const g = new FakeGain();
      gains.push(g);
      return g;
    },
    createBiquadFilter: () => new FakeFilter(),
    createStereoPanner: () => {
      const p = new FakePanner();
      panners.push(p);
      return p;
    },
    createBufferSource: () => {
      const s = new FakeSource();
      sources.push(s);
      return s;
    },
    decodeAudioData: vi.fn(async () => ({ duration: 30 })),
    resume: vi.fn(async function (this: { state: string }) {
      ctx.state = "running";
    }),
    close: vi.fn(async () => undefined),
  };
  return { ctx, sources, panners, gains };
}

const ASSETS: SoundAsset[] = [
  { id: "music.seedling.spring", kind: "music", url: "u/a", loop: true },
  { id: "music.thriving.spring", kind: "music", url: "u/b", loop: true },
  { id: "sfx.growth", kind: "sfx", url: "u/g" },
  { id: "sfx.ring", kind: "sfx", url: "u/r" },
  { id: "sfx.ui_click", kind: "sfx", url: "u/c" },
];

const okFetch = vi.fn(async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(8) }));
const flush = () => new Promise((r) => setTimeout(r, 0));

function setup(state: "running" | "suspended" = "running", fetchImpl = okFetch) {
  const fake = makeContext(state);
  const errors: string[] = [];
  const engine = new SoundscapeEngine({
    createContext: () => fake.ctx as unknown as AudioContext,
    fetchImpl: fetchImpl as unknown as typeof fetch,
    onError: (m) => errors.push(m),
  });
  engine.load(ASSETS);
  return { ...fake, engine, errors };
}

describe("SoundscapeEngine", () => {
  it("is silent and creates no audio until unmuted", async () => {
    const { engine, sources } = setup();
    await engine.unlock();
    await flush();
    expect(sources).toHaveLength(0); // default is muted
    engine.setState({ muted: false });
    await flush();
    expect(sources).toHaveLength(1);
    expect(sources[0]?.loop).toBe(true);
    expect(sources[0]?.started).toBe(1);
  });

  it("waits for a user gesture when the context is suspended", async () => {
    const { engine, sources, ctx } = setup("suspended");
    engine.setState({ muted: false });
    await flush();
    expect(sources).toHaveLength(0);
    await engine.unlock();
    await flush();
    expect(ctx.resume).toHaveBeenCalled();
    expect(sources).toHaveLength(1);
  });

  it("crossfades to the new stem when the mood changes", async () => {
    const { engine, sources } = setup();
    engine.setState({ muted: false });
    await engine.unlock();
    await flush();
    engine.setState({ mood: "thriving" });
    await flush();
    expect(sources).toHaveLength(2);
    expect(sources[0]?.stopped).toBe(1); // old stem fades out and stops
    expect(sources[1]?.started).toBe(1);
    engine.setState({ mood: "thriving" }); // no change: nothing new
    await flush();
    expect(sources).toHaveLength(2);
  });

  it("applies mute to the master gain and fades stems out", async () => {
    const { engine, sources, gains } = setup();
    engine.setState({ muted: false });
    await engine.unlock();
    await flush();
    const master = gains[0];
    expect((master?.gain.targets.at(-1) ?? 0) > 0).toBe(true);
    engine.setState({ muted: true });
    expect(master?.gain.targets.at(-1)).toBe(0);
    expect(sources[0]?.stopped).toBe(1);
  });

  it("plays one-shots panned to the plant, and skips decorative ones under reduced motion", async () => {
    const { engine, panners, sources } = setup();
    engine.setState({ muted: false });
    await engine.unlock();
    await flush();
    const before = sources.length;
    expect(engine.play({ type: "growth" }, { worldX: -5, halfWidth: 10 })).toBe(true);
    await flush();
    expect(sources.length).toBe(before + 1);
    expect(panners[0]?.pan.value).toBeCloseTo(-0.4);

    engine.setState({ reducedMotion: true });
    expect(engine.play({ type: "growth" })).toBe(false);
    expect(engine.play({ type: "ring" })).toBe(true); // a ring is a call, not decoration
    await flush();
    const ui = panners.length;
    expect(engine.play({ type: "ui", action: "click" }, { worldX: 3, halfWidth: 10 })).toBe(true);
    await flush();
    expect(panners.length).toBe(ui); // reduced motion: no panning
  });

  it("does not play anything when muted or when the effect is missing", async () => {
    const { engine } = setup();
    await engine.unlock();
    expect(engine.play({ type: "ring" })).toBe(false); // muted
    engine.setState({ muted: false });
    expect(engine.play({ type: "bloom" })).toBe(false); // no sfx.bloom in the manifest
  });

  it("stays silent and reports once when files fail to load", async () => {
    const failing = vi.fn(async () => ({ ok: false, arrayBuffer: async () => new ArrayBuffer(0) }));
    const { engine, sources, errors } = setup("running", failing);
    engine.setState({ muted: false });
    await engine.unlock();
    await flush();
    engine.setState({ season: "spring" });
    await flush();
    expect(sources).toHaveLength(0);
    expect(errors).toEqual(["could not load music.seedling.spring"]);
  });

  it("never throws when the context cannot be created, and disposes cleanly", async () => {
    const errors: string[] = [];
    const broken = new SoundscapeEngine({
      createContext: () => {
        throw new Error("no audio");
      },
      onError: (m) => errors.push(m),
    });
    broken.load(ASSETS);
    broken.setState({ muted: false });
    await expect(broken.unlock()).resolves.toBeUndefined();
    expect(broken.play({ type: "ring" })).toBe(false);
    expect(errors).toEqual(["audio is not available in this browser"]);

    const { engine, ctx } = setup();
    engine.setState({ muted: false });
    await engine.unlock();
    engine.dispose();
    engine.setState({ mood: "wilting" });
    expect(ctx.close).toHaveBeenCalled();
  });
});
