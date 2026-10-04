/**
 * Pure mixing rules for the living soundscape: garden state, time of day and season in, stem
 * gains out. No Web Audio here, so every rule is unit tested. Stem ids match the catalogue in
 * `sg_core.soundscape.catalog` (`music.<mood>.<season>`, `sfx.<name>`).
 */

export const MOODS = ["seedling", "thriving", "wilting", "blooming"] as const;
export type Mood = (typeof MOODS)[number];

export const SEASONS = ["spring", "summer", "autumn", "winter"] as const;
export type Season = (typeof SEASONS)[number];

export type DayPart = "dawn" | "day" | "dusk" | "night";

export const SFX_NAMES = [
  "growth",
  "bloom",
  "wilt",
  "ring",
  "ui_click",
  "ui_open",
  "ui_close",
  "recap_start",
] as const;
export type SfxName = (typeof SFX_NAMES)[number];

/** The slice of a plant the mood needs. Matches `PlantState` in `@sg/contracts`. */
export interface PlantAudioInput {
  stage: string;
  wilting?: boolean;
}

export interface GardenAudioState {
  plants: readonly PlantAudioInput[];
  /** A plant just flowered (a transfer or retained stage was reached): lift the mood briefly. */
  celebrating?: boolean;
}

const MIN_ASSESSED_FOR_MOOD = 3;
const WILTING_SHARE = 0.3;
const THRIVING_SHARE = 0.5;
const GROWN_STAGES = new Set(["independent", "transfer", "retained"]);

/** Mood follows evidence, never effort: a garden of unassessed plants is a seedling garden. */
export function moodFor(state: GardenAudioState): Mood {
  const assessed = state.plants.filter((p) => p.stage !== "unassessed");
  if (state.celebrating) return "blooming";
  if (assessed.length < MIN_ASSESSED_FOR_MOOD) return "seedling";
  const wilting = assessed.filter((p) => p.wilting).length / assessed.length;
  if (wilting >= WILTING_SHARE) return "wilting";
  const grown = assessed.filter((p) => GROWN_STAGES.has(p.stage)).length / assessed.length;
  return grown >= THRIVING_SHARE ? "thriving" : "seedling";
}

/** Northern-hemisphere meteorological seasons, from the learner's local date. */
export function seasonFor(date: Date): Season {
  const m = date.getMonth(); // 0 = January
  if (m >= 2 && m <= 4) return "spring";
  if (m >= 5 && m <= 7) return "summer";
  if (m >= 8 && m <= 10) return "autumn";
  return "winter";
}

export function dayPartFor(hour: number): DayPart {
  const h = ((hour % 24) + 24) % 24;
  if (h >= 5 && h < 8) return "dawn";
  if (h >= 8 && h < 18) return "day";
  if (h >= 18 && h < 21) return "dusk";
  return "night";
}

export function stemId(mood: Mood, season: Season): string {
  return `music.${mood}.${season}`;
}

export function sfxId(name: SfxName): string {
  return `sfx.${name}`;
}

export interface MixInput {
  mood: Mood;
  season: Season;
  dayPart: DayPart;
  muted: boolean;
  /** 0..1, the learner's volume slider. */
  volume: number;
  reducedMotion: boolean;
}

export interface Mix {
  /** Target gain per music stem id; every stem not listed is silent. */
  stems: Record<string, number>;
  /** Overall level after mute, volume and time-of-day. */
  master: number;
  /** Low-pass cutoff in Hz: darker at night, brighter by day. */
  cutoffHz: number;
  /** Seconds for stems to crossfade. Reduced motion shortens it and stills spatial movement. */
  crossfadeSeconds: number;
  /** Whether decorative one-shots (growth, bloom, wilt) may play. UI sounds are unaffected. */
  decorativeSfx: boolean;
  /** Whether spatial effects pan across the stereo field. */
  spatial: boolean;
}

const DAY_PART_LEVEL: Record<DayPart, number> = { dawn: 0.8, day: 1, dusk: 0.8, night: 0.55 };
const DAY_PART_CUTOFF: Record<DayPart, number> = {
  dawn: 6000,
  day: 12000,
  dusk: 5000,
  night: 2400,
};
/** Ambient music never exceeds this, so voice sessions and speech stay in front. */
export const MUSIC_CEILING = 0.35;
const REDUCED_MOTION_FACTOR = 0.6;

export function clamp01(n: number): number {
  return Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : 0;
}

export function computeMix(input: MixInput): Mix {
  const level = input.muted
    ? 0
    : clamp01(input.volume) *
      MUSIC_CEILING *
      DAY_PART_LEVEL[input.dayPart] *
      (input.reducedMotion ? REDUCED_MOTION_FACTOR : 1);
  return {
    stems: { [stemId(input.mood, input.season)]: 1 },
    master: level,
    cutoffHz: DAY_PART_CUTOFF[input.dayPart],
    crossfadeSeconds: input.reducedMotion ? 0.5 : 6,
    decorativeSfx: !input.reducedMotion && !input.muted,
    spatial: !input.reducedMotion,
  };
}

/** Which one-shot a garden event should trigger, if any. */
export type GardenEvent =
  | { type: "growth"; conceptId?: string }
  | { type: "bloom"; conceptId?: string }
  | { type: "wilt"; conceptId?: string }
  | { type: "ring" }
  | { type: "ui"; action: "click" | "open" | "close" }
  | { type: "recap_start" };

export function sfxFor(event: GardenEvent): SfxName {
  switch (event.type) {
    case "growth":
    case "bloom":
    case "wilt":
    case "ring":
    case "recap_start":
      return event.type;
    case "ui":
      return `ui_${event.action}`;
  }
}

/** Decorative events are skipped under reduced motion; rings and UI feedback always play. */
export function isDecorative(event: GardenEvent): boolean {
  return event.type === "growth" || event.type === "bloom" || event.type === "wilt";
}

/** Horizontal pan in [-1, 1] from a world x position and the half-width of the garden. */
export function panFor(x: number, halfWidth: number): number {
  if (!(halfWidth > 0)) return 0;
  return Math.max(-1, Math.min(1, x / halfWidth)) * 0.8;
}
