"use client";

import type { Character } from "@sg/contracts";
import type { LipSyncDriver } from "@sg/three/avatar";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { CharacterAvatar } from "@/components/character/character-avatar";
import {
  setVoiceMuted,
  speechSupported,
  useSpeechInput,
  useVoiceMuted,
} from "@/lib/practice/speech";

/** Shared pieces of the practice stages: portrait, transcript, answer box, voice toggle. */

export interface Turn {
  id: number;
  who: Character | "you";
  text: string;
}

const NAMES: Record<Character, string> = {
  drona: "Drona",
  arjuna: "Arjuna",
  vidura: "Vidura",
  bhima: "Bhima",
  krishna: "Krishna",
  sanjaya: "Sanjaya",
};

export const nameOf = (c: Character) => NAMES[c];

export function CoachPortrait({
  character,
  driver,
  status,
  emphasis = true,
  className = "h-72",
  size = 200,
}: {
  character: Character;
  driver: LipSyncDriver;
  status: string;
  emphasis?: boolean;
  className?: string;
  size?: number;
}) {
  return (
    <div
      className={`relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-b from-dusk to-night transition-opacity duration-500 ${className} ${emphasis ? "" : "opacity-70"}`}
      data-testid="avatar-stage"
    >
      <div className="grid h-full w-full place-items-center">
        <CharacterAvatar character={character} size={size} driver={driver} />
      </div>
      <span
        className="absolute left-3 top-3 rounded-full bg-night/70 px-2.5 py-1 text-xs backdrop-blur"
        role="status"
      >
        {status}
      </span>
    </div>
  );
}

export function VoiceToggle() {
  const muted = useVoiceMuted();
  if (!speechSupported()) return null;
  return (
    <button
      type="button"
      aria-pressed={!muted}
      onClick={() => setVoiceMuted(!muted)}
      className="rounded-lg border border-white/10 px-2.5 py-1 text-xs text-foreground/70 outline-none hover:border-white/25 focus-visible:ring-2 focus-visible:ring-glow"
    >
      {muted ? "Voice off" : "Voice on"}
    </button>
  );
}

export function Transcript({ turns, empty }: { turns: Turn[]; empty: string }) {
  const box = useRef<HTMLElement>(null);
  useEffect(() => {
    // Scroll the transcript itself, never the page.
    const el = box.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [turns.length]);
  return (
    <section
      ref={box}
      aria-label="Conversation"
      className="glass flex max-h-80 min-h-28 flex-col gap-2 overflow-y-auto rounded-2xl p-4 text-sm leading-relaxed"
      role="log"
      aria-live="polite"
    >
      {turns.length === 0 && <p className="text-foreground/50">{empty}</p>}
      {turns.map((t) => (
        <p key={t.id} className={t.who === "you" ? "text-foreground/75" : ""}>
          <span
            className={`mr-2 text-xs uppercase tracking-widest ${t.who === "you" ? "text-moss" : "text-glow"}`}
          >
            {t.who === "you" ? "You" : NAMES[t.who]}
          </span>
          {t.text}
        </p>
      ))}
    </section>
  );
}

/**
 * The learner's turn: type, or speak with the microphone where the browser supports it.
 * Enter sends; Shift+Enter starts a new line.
 */
export function AnswerBox({
  onSubmit,
  disabled,
  placeholder,
  value,
  onChange,
  submitLabel = "Send",
  children,
}: {
  onSubmit: (text: string) => void;
  disabled: boolean;
  placeholder: string;
  value: string;
  onChange: (text: string) => void;
  submitLabel?: string;
  /** Extra buttons (hint, skip) after Send. */
  children?: ReactNode;
}) {
  const valueRef = useRef(value);
  useEffect(() => {
    valueRef.current = value;
  });
  const mic = useSpeechInput((phrase) => {
    const current = valueRef.current;
    onChange(current ? `${current.trimEnd()} ${phrase}` : phrase);
  });
  const { listening, stop } = mic;
  useEffect(() => {
    if (disabled && listening) stop();
  }, [disabled, listening, stop]);

  const send = () => {
    const text = value.trim();
    if (!text || disabled) return;
    if (listening) stop();
    onSubmit(text);
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        send();
      }}
      className="glass flex flex-col gap-2 rounded-2xl p-3"
    >
      <label htmlFor="practice-answer" className="sr-only">
        Your answer
      </label>
      <textarea
        id="practice-answer"
        value={listening && mic.interim ? `${value}${value ? " " : ""}${mic.interim}` : value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            send();
          }
        }}
        rows={3}
        maxLength={4000}
        placeholder={placeholder}
        disabled={disabled}
        className="w-full resize-y rounded-xl border border-white/15 bg-night/70 p-3 text-sm outline-none focus-visible:border-glow focus-visible:ring-2 focus-visible:ring-glow/40 disabled:opacity-60"
      />
      {mic.error && (
        <p role="alert" className="text-xs text-ember">
          {mic.error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="rounded-xl bg-moss px-4 py-2 text-sm font-medium text-night outline-none hover:brightness-110 focus-visible:ring-2 focus-visible:ring-glow disabled:opacity-50"
        >
          {submitLabel}
        </button>
        {mic.supported && (
          <button
            type="button"
            onClick={listening ? stop : mic.start}
            disabled={disabled}
            aria-pressed={listening}
            className={`rounded-xl border px-4 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-glow disabled:opacity-50 ${
              listening
                ? "border-ember/60 bg-ember/15 text-ember"
                : "border-white/15 hover:border-white/30"
            }`}
          >
            {listening ? "Stop listening" : "Answer out loud"}
          </button>
        )}
        {children}
        <span className="ml-auto hidden text-xs text-foreground/40 sm:inline">
          Enter to send · Shift+Enter for a new line
        </span>
      </div>
    </form>
  );
}

export function PrimaryButton({
  children,
  onClick,
  disabled,
  tone = "glow",
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  tone?: "glow" | "ember" | "moss";
}) {
  const tones = {
    glow: "bg-glow/90 hover:bg-glow focus-visible:ring-glow",
    ember: "bg-ember/90 hover:bg-ember focus-visible:ring-ember",
    moss: "bg-moss hover:brightness-110 focus-visible:ring-glow",
  } as const;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-xl px-5 py-2.5 text-sm font-medium text-night outline-none focus-visible:ring-2 disabled:opacity-50 ${tones[tone]}`}
    >
      {children}
    </button>
  );
}

export function SecondaryButton({
  children,
  onClick,
  disabled,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-xl border border-white/15 px-4 py-2 text-sm outline-none hover:border-white/30 focus-visible:ring-2 focus-visible:ring-glow disabled:opacity-40"
    >
      {children}
    </button>
  );
}

export interface EarnedItem {
  plantTitle: string;
  dimension: string;
  outcome: "demonstrated" | "partial";
  assisted: boolean;
  quote: string;
}

/** What a finished session added to the garden. */
export function SessionSummary({
  title,
  earned,
  notes = [],
  onAgain,
  againLabel = "Practise again",
  saved = true,
}: {
  title: string;
  earned: EarnedItem[];
  notes?: string[];
  onAgain: () => void;
  againLabel?: string;
  saved?: boolean;
}) {
  return (
    <section aria-label="Session summary" className="glass rounded-2xl p-5" role="status">
      <p className="text-[0.7rem] uppercase tracking-[0.22em] text-glow">Session saved</p>
      <h2 className="mt-1 text-xl font-semibold">{title}</h2>
      {earned.length === 0 ? (
        <p className="mt-2 text-sm text-foreground/70">
          Nothing grew this time: your garden only grows from what you show. Try again, or ask for
          the key ideas first.
        </p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {earned.map((e, i) => (
            <li key={i} className="rounded-xl bg-white/5 px-3 py-2 text-sm">
              <p className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-medium">{e.plantTitle}</span>
                <span className="text-xs capitalize text-foreground/60">{e.dimension}</span>
                <span
                  className={`text-xs ${e.assisted ? "text-ember" : e.outcome === "demonstrated" ? "text-moss" : "text-glow"}`}
                >
                  {e.assisted
                    ? "assisted"
                    : e.outcome === "demonstrated"
                      ? "independent"
                      : "partial"}
                </span>
              </p>
              {e.quote && <p className="mt-1 line-clamp-2 text-foreground/70">“{e.quote}”</p>}
            </li>
          ))}
        </ul>
      )}
      {notes.map((n) => (
        <p key={n} className="mt-2 text-sm text-foreground/70">
          {n}
        </p>
      ))}
      {!saved && (
        <p role="alert" className="mt-2 text-sm text-ember">
          This browser did not let the session be saved, so your garden will not remember it.
        </p>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <Link
          href="/garden"
          className="rounded-xl bg-moss px-4 py-2 text-sm font-medium text-night outline-none hover:brightness-110 focus-visible:ring-2 focus-visible:ring-glow"
        >
          Open your garden
        </Link>
        <SecondaryButton onClick={onAgain}>{againLabel}</SecondaryButton>
      </div>
    </section>
  );
}

export function LoadingPanel({ label = "Getting things ready…" }: { label?: string }) {
  return (
    <div className="grid min-h-60 place-items-center rounded-2xl border border-white/10 text-sm text-foreground/60">
      <span className="flex items-center gap-2">
        <span className="size-2 animate-pulse rounded-full bg-glow" aria-hidden />
        {label}
      </span>
    </div>
  );
}

/** The conversation so far, with stable `add` and `clear`. */
export function useTurnLog(): [Turn[], (who: Turn["who"], text: string) => void, () => void] {
  const [turns, setTurns] = useState<Turn[]>([]);
  const next = useRef(1);
  const add = useCallback((who: Turn["who"], text: string) => {
    const id = next.current++;
    setTurns((t) => [...t, { id, who, text }]);
  }, []);
  const clear = useCallback(() => setTurns([]), []);
  return [turns, add, clear];
}
