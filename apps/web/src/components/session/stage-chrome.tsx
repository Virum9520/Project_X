"use client";

import type { useLipSync } from "@sg/three/avatar";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import type { StageState } from "@/lib/session/stage";

import { DiagramPlaceholder, EditorPlaceholder, QuestionCardView } from "./stage-parts";

/** Call lifecycle shared by every voice stage. */
export type Phase = "idle" | "starting" | "live" | "ended" | "interrupted";

export type LipDriver = ReturnType<typeof useLipSync>;

/** Phase state plus a ref mirror, so ElevenLabs callbacks always read the latest phase. */
export function usePhase() {
  const [phase, setPhase] = useState<Phase>("idle");
  const phaseRef = useRef<Phase>("idle");
  const setPhaseBoth = useCallback((next: Phase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);
  return { phase, phaseRef, setPhaseBoth };
}

/**
 * Mouth-level fallback while the agent talks and no alignment is playing: drives the driver
 * returned by `pick()` from the output volume and zeroes every driver otherwise.
 */
export function useMouthLevelFallback({
  live,
  speaking,
  outputVolume,
  drivers,
  pick,
}: {
  live: boolean;
  speaking: boolean;
  outputVolume: () => number;
  drivers: readonly LipDriver[];
  pick: () => LipDriver;
}) {
  useEffect(() => {
    if (!live || !speaking) {
      for (const d of drivers) d.setLevel(0);
      return;
    }
    const active = pick();
    let frame = 0;
    const tick = () => {
      active.setLevel(outputVolume());
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      active.setLevel(0);
    };
  }, [live, speaking, outputVolume, drivers, pick]);
}

export function StageHeader({
  eyebrow,
  title,
  subtitle,
  isMock,
  liveConnected,
  extra,
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
  isMock: boolean;
  liveConnected: boolean;
  /** Extra controls placed before the status chips (e.g. sound controls). */
  extra?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p className="text-xs uppercase tracking-[0.3em] text-glow">{eyebrow}</p>
        <h1 className="mt-1 text-2xl font-semibold sm:text-3xl">{title}</h1>
        {subtitle && <p className="mt-1 font-mono text-xs text-foreground/60">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2 text-xs text-foreground/60">
        {extra}
        {isMock && (
          <span className="rounded-full bg-ember/15 px-2.5 py-1 text-ember ring-1 ring-ember/40">
            Sample garden
          </span>
        )}
        <span
          className={`rounded-full px-2.5 py-1 ring-1 ${liveConnected ? "text-moss ring-moss/40" : "ring-white/15"}`}
        >
          {liveConnected ? "Live garden updates on" : "Live updates idle"}
        </span>
      </div>
    </header>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="rounded-xl border border-ember/40 bg-ember/10 px-4 py-2 text-sm text-ember"
    >
      {message}
    </p>
  );
}

export function StatusNote({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="rounded-xl bg-white/5 px-4 py-2 text-sm">
      {children}
    </p>
  );
}

/** Start / End / Mute buttons. `noun` is "session" or "interview". */
export function CallControls({
  noun,
  phase,
  isMuted,
  onStart,
  onEnd,
  onToggleMute,
}: {
  noun: string;
  phase: Phase;
  isMuted: boolean;
  onStart: () => void;
  onEnd: () => void;
  onToggleMute: () => void;
}) {
  const busy = phase === "starting";
  if (phase !== "live") {
    return (
      <button
        type="button"
        onClick={onStart}
        disabled={busy}
        className="rounded-xl bg-glow/90 px-5 py-2.5 text-sm font-medium text-night outline-none hover:bg-glow focus-visible:ring-2 focus-visible:ring-glow disabled:opacity-50"
      >
        {busy
          ? "Starting…"
          : phase === "ended" || phase === "interrupted"
            ? "Start again"
            : `Start ${noun}`}
      </button>
    );
  }
  return (
    <>
      <button
        type="button"
        onClick={onEnd}
        className="rounded-xl bg-ember/90 px-5 py-2.5 text-sm font-medium text-night outline-none hover:bg-ember focus-visible:ring-2 focus-visible:ring-ember"
      >
        End {noun}
      </button>
      <button
        type="button"
        onClick={onToggleMute}
        aria-pressed={isMuted}
        className="rounded-xl border border-white/15 px-4 py-2.5 text-sm outline-none hover:border-white/30 focus-visible:ring-2 focus-visible:ring-glow"
      >
        {isMuted ? "Unmute" : "Mute"}
      </button>
    </>
  );
}

/** Shown after a call ends; `children` is the message before the garden link. */
export function SavedNotice({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="rounded-xl bg-white/5 px-4 py-3 text-sm">
      {children}{" "}
      <Link href="/garden" className="text-glow underline underline-offset-2">
        Open your garden
      </Link>
    </p>
  );
}

/** The question card, editor and diagram panels a stage's client tools can open. */
export function StagePanels({
  stage,
  onDismiss,
}: {
  stage: Pick<StageState, "card" | "editor" | "diagram">;
  onDismiss: (what: "card" | "editor" | "diagram") => void;
}) {
  return (
    <>
      {stage.card && <QuestionCardView card={stage.card} onClose={() => onDismiss("card")} />}
      {stage.editor && (
        <EditorPlaceholder
          problemId={stage.editor.problem_id}
          language={stage.editor.language}
          onClose={() => onDismiss("editor")}
        />
      )}
      {stage.diagram && (
        <DiagramPlaceholder
          id={stage.diagram.id}
          caption={stage.diagram.caption}
          onClose={() => onDismiss("diagram")}
        />
      )}
    </>
  );
}
