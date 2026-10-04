/** Per-viewer sound preferences, kept in localStorage. Every access is guarded: storage can be
 * blocked (private windows, cleared site data), and the engine must work without it. */

export interface SoundPrefs {
  muted: boolean;
  volume: number;
}

export const PREFS_KEY = "sg.soundscape.v1";
export const DEFAULT_PREFS: SoundPrefs = { muted: true, volume: 0.7 };

export function parsePrefs(raw: string | null): SoundPrefs {
  if (!raw) return { ...DEFAULT_PREFS };
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null) return { ...DEFAULT_PREFS };
    const v = value as Record<string, unknown>;
    const volume = typeof v.volume === "number" && Number.isFinite(v.volume) ? v.volume : 0.7;
    return {
      muted: typeof v.muted === "boolean" ? v.muted : true,
      volume: Math.min(1, Math.max(0, volume)),
    };
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

export function readPrefs(storage?: Pick<Storage, "getItem">): SoundPrefs {
  try {
    const store = storage ?? (typeof localStorage === "undefined" ? undefined : localStorage);
    return parsePrefs(store ? store.getItem(PREFS_KEY) : null);
  } catch {
    return { ...DEFAULT_PREFS };
  }
}

export function writePrefs(prefs: SoundPrefs, storage?: Pick<Storage, "setItem">): void {
  try {
    const store = storage ?? (typeof localStorage === "undefined" ? undefined : localStorage);
    store?.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* preference not remembered; that is fine */
  }
}
