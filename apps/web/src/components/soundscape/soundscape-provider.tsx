"use client";

import {
  type DayPart,
  type EngineState,
  type GardenAudioState,
  type GardenEvent,
  SoundscapeEngine,
  dayPartFor,
  moodFor,
  readPrefs,
  seasonFor,
  writePrefs,
} from "@sg/audio";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { loadSoundManifest } from "./actions";

interface SoundscapeApi {
  /** False until the client has mounted; render nothing audio-specific before then. */
  ready: boolean;
  muted: boolean;
  volume: number;
  /** Sound is opt-in: the first call is the user gesture that unlocks audio. */
  toggleMuted: () => void;
  setVolume: (v: number) => void;
  /** Fire a one-shot (growth, bloom, wilt, ring, UI). Safe to call when muted or unavailable. */
  play: (event: GardenEvent, opts?: { worldX?: number; halfWidth?: number }) => void;
  reducedMotion: boolean;
  /** Set when the manifest could not be loaded (nothing generated yet, or the API is down). */
  unavailable: boolean;
}

const Context = createContext<SoundscapeApi | null>(null);

/** Null outside a provider, so components can offer sound only where the soundscape exists. */
export function useSoundscape(): SoundscapeApi | null {
  return useContext(Context);
}

const DAY_PART_REFRESH_MS = 5 * 60_000;

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

function useDayPart(): { dayPart: DayPart; season: ReturnType<typeof seasonFor> } {
  const read = () => {
    const now = new Date();
    return { dayPart: dayPartFor(now.getHours()), season: seasonFor(now) };
  };
  const [value, setValue] = useState(read);
  useEffect(() => {
    const id = window.setInterval(() => setValue(read()), DAY_PART_REFRESH_MS);
    return () => window.clearInterval(id);
  }, []);
  return value;
}

/**
 * Client-only soundscape. Wrap the part of the app that shows the garden; pass the garden state
 * and the engine follows it (mood from evidence, season and time of day from the local clock).
 * Nothing audible happens until the learner turns sound on; mute and volume are remembered per
 * browser, and `prefers-reduced-motion` quiets the music and drops decorative effects.
 */
export function SoundscapeProvider({
  garden,
  children,
}: {
  garden: GardenAudioState;
  children: ReactNode;
}) {
  const engineRef = useRef<SoundscapeEngine | null>(null);
  const manifestRequested = useRef(false);
  const [ready, setReady] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [prefs, setPrefs] = useState({ muted: true, volume: 0.7 });
  const reducedMotion = useReducedMotion();
  const { dayPart, season } = useDayPart();
  const mood = useMemo(() => moodFor(garden), [garden]);

  useEffect(() => {
    const engine = new SoundscapeEngine({ onError: () => setUnavailable(true) });
    engineRef.current = engine;
    // Browser-only state (localStorage) is read after mount so server and client markup match.
    /* eslint-disable react-hooks/set-state-in-effect */
    setPrefs(readPrefs());
    setReady(true);
    /* eslint-enable react-hooks/set-state-in-effect */
    return () => {
      engine.dispose();
      engineRef.current = null;
      manifestRequested.current = false;
    };
  }, []);

  useEffect(() => {
    const patch: Partial<EngineState> = {
      mood,
      season,
      dayPart,
      muted: prefs.muted,
      volume: prefs.volume,
      reducedMotion,
    };
    engineRef.current?.setState(patch);
  }, [mood, season, dayPart, prefs, reducedMotion, ready]);

  const ensureManifest = useCallback(async () => {
    if (manifestRequested.current) return;
    manifestRequested.current = true;
    try {
      const manifest = await loadSoundManifest();
      if (!manifest || manifest.assets.length === 0) {
        manifestRequested.current = false;
        setUnavailable(true);
        return;
      }
      engineRef.current?.load(manifest.assets);
      setUnavailable(false);
    } catch {
      manifestRequested.current = false;
      setUnavailable(true);
    }
  }, []);

  const toggleMuted = useCallback(() => {
    const next = { ...prefs, muted: !prefs.muted };
    setPrefs(next);
    writePrefs(next);
    if (!next.muted) {
      // Inside the click handler: this is the gesture browsers require to start audio.
      void engineRef.current?.unlock();
      void ensureManifest();
    }
  }, [prefs, ensureManifest]);

  const setVolume = useCallback(
    (volume: number) => {
      const next = { ...prefs, volume };
      setPrefs(next);
      writePrefs(next);
    },
    [prefs],
  );

  const play = useCallback<SoundscapeApi["play"]>((event, opts) => {
    engineRef.current?.play(event, opts);
  }, []);

  const api = useMemo<SoundscapeApi>(
    () => ({
      ready,
      muted: prefs.muted,
      volume: prefs.volume,
      toggleMuted,
      setVolume,
      play,
      reducedMotion,
      unavailable,
    }),
    [ready, prefs, toggleMuted, setVolume, play, reducedMotion, unavailable],
  );

  return <Context.Provider value={api}>{children}</Context.Provider>;
}
