/**
 * Browser audio engine for the living soundscape. Client-only: nothing here runs at import time,
 * and the `AudioContext` is created on first use, so server rendering never touches it.
 *
 * It is a thin player over the pure rules in `mix.ts`: one looping music stem at a time with
 * crossfades, a master gain (mute, volume, time of day), a low-pass filter, and one-shot effects,
 * optionally panned to where a plant sits. If the manifest is missing or a file fails to load, the
 * engine stays silent; it never throws into the page.
 */

import {
  type DayPart,
  type GardenEvent,
  type Mix,
  type Mood,
  type Season,
  computeMix,
  isDecorative,
  panFor,
  sfxFor,
  sfxId,
  stemId,
} from "./mix";

export interface SoundAsset {
  id: string;
  kind: "music" | "sfx";
  url: string;
  loop?: boolean;
}

export interface EngineState {
  mood: Mood;
  season: Season;
  dayPart: DayPart;
  muted: boolean;
  volume: number;
  reducedMotion: boolean;
}

export interface EngineOptions {
  /** Defaults to `new AudioContext()`; tests inject a fake. */
  createContext?: () => AudioContext;
  /** Defaults to global `fetch`. */
  fetchImpl?: typeof fetch;
  onError?: (message: string) => void;
}

export const DEFAULT_STATE: EngineState = {
  mood: "seedling",
  season: "spring",
  dayPart: "day",
  muted: true, // sound is opt-in
  volume: 0.7,
  reducedMotion: false,
};

const MASTER_SMOOTHING = 0.25;
const MAX_CONCURRENT_SFX = 6;

interface ActiveStem {
  id: string;
  gain: GainNode;
  source: AudioBufferSourceNode;
}

export class SoundscapeEngine {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private filter: BiquadFilterNode | null = null;
  private assets = new Map<string, SoundAsset>();
  private buffers = new Map<string, Promise<AudioBuffer | null>>();
  private stems: ActiveStem[] = [];
  private state: EngineState = { ...DEFAULT_STATE };
  private activeSfx = 0;
  private disposed = false;
  private warned = new Set<string>();

  constructor(private readonly options: EngineOptions = {}) {}

  /** Register what can be played. Replaces any previous manifest (signed URLs expire). */
  load(assets: readonly SoundAsset[]): void {
    this.assets = new Map(assets.map((a) => [a.id, a]));
    this.buffers.clear();
    void this.applyMusic();
  }

  get isSupported(): boolean {
    return this.options.createContext !== undefined || typeof AudioContext !== "undefined";
  }

  getState(): EngineState {
    return { ...this.state };
  }

  currentMix(): Mix {
    return computeMix(this.state);
  }

  /** Call from a user gesture (the sound toggle): browsers keep audio suspended until then. */
  async unlock(): Promise<void> {
    const ctx = this.ensureContext();
    if (ctx && ctx.state === "suspended") {
      try {
        await ctx.resume();
      } catch {
        this.warn("resume", "audio could not start");
      }
    }
    void this.applyMusic();
  }

  setState(patch: Partial<EngineState>): void {
    if (this.disposed) return;
    const before = this.state;
    this.state = { ...this.state, ...patch };
    this.applyMaster();
    if (before.mood !== this.state.mood || before.season !== this.state.season) {
      void this.applyMusic();
    }
    if (this.state.muted && !before.muted) this.fadeOutAll(0.3);
    if (!this.state.muted && before.muted) void this.applyMusic();
  }

  /** Play a one-shot for a garden event. Returns whether anything was started. */
  play(event: GardenEvent, opts: { worldX?: number; halfWidth?: number } = {}): boolean {
    const mix = computeMix(this.state);
    if (this.state.muted || this.disposed) return false;
    if (isDecorative(event) && !mix.decorativeSfx) return false;
    if (this.activeSfx >= MAX_CONCURRENT_SFX) return false;
    const asset = this.assets.get(sfxId(sfxFor(event)));
    const ctx = this.ensureContext();
    if (!asset || !ctx || ctx.state !== "running") return false;
    this.activeSfx += 1;
    void this.bufferFor(asset).then((buffer) => {
      const master = this.master;
      if (!buffer || !master || this.disposed || this.state.muted) {
        this.activeSfx -= 1;
        return;
      }
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      let tail: AudioNode = source;
      if (
        mix.spatial &&
        opts.worldX !== undefined &&
        typeof ctx.createStereoPanner === "function"
      ) {
        const panner = ctx.createStereoPanner();
        panner.pan.value = panFor(opts.worldX, opts.halfWidth ?? 1);
        tail.connect(panner);
        tail = panner;
      }
      // Effects sit a little above the bed of music but below speech.
      const gain = ctx.createGain();
      gain.gain.value = 0.9;
      tail.connect(gain);
      gain.connect(master);
      source.onended = () => {
        this.activeSfx -= 1;
        gain.disconnect();
      };
      source.start();
    });
    return true;
  }

  dispose(): void {
    this.disposed = true;
    for (const s of this.stems) this.stopStem(s);
    this.stems = [];
    const ctx = this.ctx;
    this.ctx = null;
    this.master = null;
    this.filter = null;
    if (ctx && ctx.state !== "closed") void ctx.close().catch(() => undefined);
  }

  // ── internals ──

  private warn(key: string, message: string): void {
    if (this.warned.has(key)) return;
    this.warned.add(key);
    this.options.onError?.(message);
  }

  private ensureContext(): AudioContext | null {
    if (this.disposed) return null;
    if (this.ctx) return this.ctx;
    try {
      const ctx = this.options.createContext
        ? this.options.createContext()
        : typeof AudioContext !== "undefined"
          ? new AudioContext()
          : null;
      if (!ctx) return null;
      const master = ctx.createGain();
      const filter = ctx.createBiquadFilter();
      filter.type = "lowpass";
      master.gain.value = 0;
      filter.connect(master);
      master.connect(ctx.destination);
      this.ctx = ctx;
      this.master = master;
      this.filter = filter;
      this.applyMaster();
      return ctx;
    } catch {
      this.warn("context", "audio is not available in this browser");
      return null;
    }
  }

  private applyMaster(): void {
    const ctx = this.ctx;
    if (!ctx || !this.master || !this.filter) return;
    const mix = computeMix(this.state);
    const now = ctx.currentTime;
    this.master.gain.setTargetAtTime(mix.master, now, MASTER_SMOOTHING);
    this.filter.frequency.setTargetAtTime(mix.cutoffHz, now, 1.5);
  }

  private async bufferFor(asset: SoundAsset): Promise<AudioBuffer | null> {
    const cached = this.buffers.get(asset.id);
    if (cached) return cached;
    const pending = (async () => {
      const ctx = this.ensureContext();
      if (!ctx) return null;
      try {
        const response = await (this.options.fetchImpl ?? fetch)(asset.url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await ctx.decodeAudioData(await response.arrayBuffer());
      } catch {
        this.warn(asset.id, `could not load ${asset.id}`);
        this.buffers.delete(asset.id); // allow a retry (a signed URL may have been refreshed)
        return null;
      }
    })();
    this.buffers.set(asset.id, pending);
    return pending;
  }

  /** Make the audible stem match the current mood and season, crossfading from the old one. */
  private async applyMusic(): Promise<void> {
    if (this.disposed || this.state.muted) return;
    const ctx = this.ctx;
    if (!ctx || ctx.state !== "running") return; // wait for `unlock()`
    const wanted = stemId(this.state.mood, this.state.season);
    const asset = this.assets.get(wanted);
    if (!asset || this.stems.some((s) => s.id === wanted)) return;
    const buffer = await this.bufferFor(asset);
    // The state may have moved on while the file was loading.
    if (!buffer || this.disposed || this.state.muted) return;
    if (stemId(this.state.mood, this.state.season) !== wanted) return;
    if (this.stems.some((s) => s.id === wanted) || !this.filter) return;

    const fade = computeMix(this.state).crossfadeSeconds;
    const now = ctx.currentTime;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.loop = true;
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(1, now + fade);
    source.connect(gain);
    gain.connect(this.filter);
    source.start();
    for (const old of [...this.stems]) this.fadeOut(old, fade);
    this.stems = [...this.stems, { id: wanted, gain, source }];
  }

  private fadeOut(stem: ActiveStem, seconds: number): void {
    const ctx = this.ctx;
    if (!ctx) return;
    const now = ctx.currentTime;
    stem.gain.gain.cancelScheduledValues(now);
    stem.gain.gain.setValueAtTime(stem.gain.gain.value, now);
    stem.gain.gain.linearRampToValueAtTime(0, now + seconds);
    stem.source.stop(now + seconds + 0.05);
    stem.source.onended = () => stem.gain.disconnect();
    this.stems = this.stems.filter((s) => s !== stem);
  }

  private fadeOutAll(seconds: number): void {
    for (const s of [...this.stems]) this.fadeOut(s, seconds);
  }

  private stopStem(stem: ActiveStem): void {
    try {
      stem.source.stop();
    } catch {
      /* already stopped */
    }
  }
}
