"use client";

import type { Character } from "@sg/contracts";
import { mockAlignment, useLipSync } from "@sg/three/avatar";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

/**
 * Voices for the coaches, from the browser's own speech synthesis, and the learner's voice in,
 * from the browser's speech recognition where it exists (Chrome, Edge, Safari). Typing always
 * works too. Nothing is recorded or uploaded by this module.
 */

interface VoiceProfile {
  pitch: number;
  rate: number;
  /** Voice names to prefer, best first. */
  prefer: RegExp[];
}

const PROFILES: Record<Character, VoiceProfile> = {
  drona: { pitch: 0.82, rate: 0.95, prefer: [/Daniel/i, /UK English Male/i, /Arthur/i, /Guy/i] },
  arjuna: { pitch: 1.0, rate: 1.03, prefer: [/Aaron/i, /US English/i, /Alex/i, /Davis|Guy/i] },
  vidura: { pitch: 0.9, rate: 0.96, prefer: [/Rishi/i, /Daniel/i, /Ravi|Prabhat/i, /Guy/i] },
  bhima: { pitch: 0.75, rate: 1.06, prefer: [/Fred/i, /Ralph/i, /Guy|Tony/i, /Male/i] },
  krishna: { pitch: 1.04, rate: 0.95, prefer: [/Rishi/i, /Ravi|Prabhat/i, /Alex/i, /Male/i] },
  sanjaya: { pitch: 0.95, rate: 0.98, prefer: [/Oliver/i, /Daniel/i, /UK English/i, /Guy/i] },
};

const MUTE_KEY = "sg.voice.muted";

export const speechSupported = () =>
  typeof window !== "undefined" &&
  "speechSynthesis" in window &&
  "SpeechSynthesisUtterance" in window;

// ── Mute preference, shared by every page ──────────────────────────────────────────────────

const muteListeners = new Set<() => void>();
function readMuted(): boolean {
  try {
    return window.localStorage.getItem(MUTE_KEY) === "1";
  } catch {
    return false;
  }
}
export function setVoiceMuted(muted: boolean) {
  try {
    window.localStorage.setItem(MUTE_KEY, muted ? "1" : "0");
  } catch {
    // Not remembered; still applies to this page.
  }
  if (muted && speechSupported()) window.speechSynthesis.cancel();
  mutedOverride = muted;
  for (const l of muteListeners) l();
}
let mutedOverride: boolean | null = null;
const getMuted = () => mutedOverride ?? readMuted();
export function useVoiceMuted(): boolean {
  return useSyncExternalStore(
    (l) => {
      muteListeners.add(l);
      return () => muteListeners.delete(l);
    },
    getMuted,
    () => false,
  );
}

// ── Speaking ───────────────────────────────────────────────────────────────────────────────

function pickVoice(character: Character): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices().filter((v) => /^en(-|_|$)/i.test(v.lang));
  if (!voices.length) return null;
  for (const pattern of PROFILES[character].prefer) {
    const match = voices.find((v) => pattern.test(v.name));
    if (match) return match;
  }
  return voices.find((v) => v.default) ?? voices[0] ?? null;
}

/** Split long text into sentences: some browsers stop speaking an utterance after ~15 s. */
function sentences(text: string): string[] {
  const parts = text.match(/[^.!?]+[.!?]+["”’)]*\s*|[^.!?]+$/g) ?? [text];
  return parts.map((s) => s.trim()).filter(Boolean);
}

// Keep utterances referenced until they finish, or some browsers drop their `end` events.
const pending = new Set<SpeechSynthesisUtterance>();
// Each speak() call supersedes the previous one; a superseded sentence chain stops itself.
let generation = 0;

export interface SpeakHooks {
  onSentence?: (sentence: string, msPerChar: number) => void;
}

/** Speak as `character`; resolves when finished, cancelled or muted. Never rejects. */
export function speak(text: string, character: Character, hooks: SpeakHooks = {}): Promise<void> {
  if (!speechSupported() || getMuted() || !text.trim()) return Promise.resolve();
  const synth = window.speechSynthesis;
  const profile = PROFILES[character];
  const voice = pickVoice(character);
  const msPerChar = 62 / profile.rate;
  const parts = sentences(text);
  const gen = ++generation;
  const interrupted = synth.speaking || synth.pending;
  if (interrupted) synth.cancel();
  return new Promise<void>((resolve) => {
    let index = 0;
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      resolve();
    };
    const next = () => {
      if (settled) return;
      if (gen !== generation || index >= parts.length || getMuted()) return finish();
      const sentence = parts[index++]!;
      const u = new SpeechSynthesisUtterance(sentence);
      if (voice) u.voice = voice;
      u.lang = voice?.lang ?? "en-US";
      u.pitch = profile.pitch;
      u.rate = profile.rate;
      pending.add(u);
      // Advance once per sentence: on `end`, on `error` (including a cancel), or on the guard
      // timer, since a browser that never fires `end` must not hang the conversation.
      let advanced = false;
      const advance = () => {
        if (advanced) return;
        advanced = true;
        window.clearTimeout(guard);
        pending.delete(u);
        next();
      };
      const guard = window.setTimeout(advance, sentence.length * msPerChar * 1.8 + 2500);
      u.onstart = () => hooks.onSentence?.(sentence, msPerChar);
      u.onend = advance;
      u.onerror = advance;
      synth.speak(u);
    };
    // Chrome can drop an utterance queued in the same tick as cancel(); wait a moment.
    if (interrupted) window.setTimeout(next, 60);
    else next();
  });
}

/** Stop talking. Anything awaiting `speak` resolves (cancel fires each utterance's `error`). */
export function stopSpeaking() {
  generation += 1;
  if (speechSupported()) window.speechSynthesis.cancel();
}

/**
 * A coach's voice for a stage: speaks, drives the portrait's pulse from the words, and keeps the
 * current caption. `say` resolves when the coach has finished.
 */
export function useCoachVoice(character: Character) {
  const lipSync = useLipSync();
  const [speaking, setSpeaking] = useState(false);
  const [caption, setCaption] = useState("");
  const turn = useRef(0);

  useEffect(() => {
    // Load the voice list early (Chrome fills it asynchronously) and stop talking on unmount.
    if (speechSupported()) window.speechSynthesis.getVoices();
    return () => {
      stopSpeaking();
      lipSync.reset();
    };
  }, [lipSync]);

  const say = useCallback(
    async (text: string) => {
      const mine = ++turn.current;
      setCaption(text);
      setSpeaking(true);
      lipSync.reset();
      const animate = (sentence: string, msPerChar: number) => {
        lipSync.reset();
        lipSync.pushAlignment(mockAlignment(sentence, msPerChar));
      };
      if (!speechSupported() || getMuted()) {
        // Silent: animate the portrait for the caption, briefly, then carry on.
        animate(text.slice(0, 160), 45);
        await new Promise((r) => window.setTimeout(r, Math.min(1800, 300 + text.length * 8)));
      } else {
        await speak(text, character, { onSentence: animate });
      }
      if (turn.current === mine) {
        setSpeaking(false);
        lipSync.reset();
      }
    },
    [character, lipSync],
  );

  const silence = useCallback(() => {
    turn.current += 1;
    stopSpeaking();
    lipSync.reset();
    setSpeaking(false);
  }, [lipSync]);

  return { lipSync, speaking, caption, say, silence };
}

// ── Listening ──────────────────────────────────────────────────────────────────────────────

interface RecognitionResult {
  isFinal: boolean;
  0: { transcript: string };
}
interface RecognitionEvent {
  resultIndex: number;
  results: ArrayLike<RecognitionResult>;
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const listeningSupported = () => recognitionCtor() !== null;

/** Speech to text into the answer box. `onFinal` gets each finished phrase. */
export function useSpeechInput(onFinal: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<Recognition | null>(null);
  const onFinalRef = useRef(onFinal);
  useEffect(() => {
    onFinalRef.current = onFinal;
  });

  const stop = useCallback(() => {
    rec.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor || rec.current) return;
    setError(null);
    const r = new Ctor();
    r.lang = "en-US";
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (event) => {
      let heard = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i]!;
        if (result.isFinal) onFinalRef.current(result[0].transcript.trim());
        else heard += result[0].transcript;
      }
      setInterim(heard);
    };
    r.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed")
        setError("Microphone access is blocked, so type your answer instead.");
      else if (event.error !== "no-speech" && event.error !== "aborted")
        setError("Speech recognition stopped. Type your answer, or try the microphone again.");
    };
    r.onend = () => {
      rec.current = null;
      setListening(false);
      setInterim("");
    };
    rec.current = r;
    try {
      r.start();
      setListening(true);
    } catch {
      rec.current = null;
      setError("Speech recognition could not start. Type your answer instead.");
    }
  }, []);

  useEffect(() => () => rec.current?.abort(), []);

  return { supported: listeningSupported(), listening, interim, error, start, stop };
}
