"use client";

import { useEffect, useState } from "react";

import type { QuestionCard, TickerEntry } from "@/lib/session/stage";

const PART_LABEL: Record<string, string> = {
  roots: "roots",
  stem: "stem",
  branches: "branches",
  blossoms: "blossoms",
};

export function QuestionCardView({ card, onClose }: { card: QuestionCard; onClose: () => void }) {
  const teach = card.kind === "teach_back";
  return (
    <section
      aria-labelledby="question-title"
      className="glass rounded-2xl border border-glow/20 p-4 sm:p-5"
      data-testid="question-card"
    >
      <header className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[0.7rem] uppercase tracking-[0.22em] text-glow">
            {teach ? "Teach-back" : "Question"}
          </p>
          <h2 id="question-title" className="mt-1 text-lg font-semibold">
            {card.title}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg px-2 py-1 text-xs text-foreground/60 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-glow"
        >
          Hide
        </button>
      </header>
      <p className="mt-2 whitespace-pre-wrap text-base leading-relaxed text-foreground/90">
        {card.body}
      </p>
    </section>
  );
}

function useElapsed(since: number | null) {
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (since === null) return;
    const tick = () => setNow(Date.now());
    const first = window.setTimeout(tick, 0);
    const id = window.setInterval(tick, 1000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(id);
    };
  }, [since]);
  return since !== null && now > 0 ? Math.max(0, Math.floor((now - since) / 1000)) : 0;
}

/**
 * Teach-back: Drona plays a confused student and the learner explains the concept. This panel
 * makes the role swap obvious, shows what the learner is saying, and lets them signal that they
 * are done. It deliberately shows no rubric or hints: that would turn explaining into reciting.
 */
export function TeachBackPanel({
  startedAt,
  heard,
  onDone,
  disabled,
}: {
  startedAt: number | null;
  heard: string;
  onDone: () => void;
  disabled: boolean;
}) {
  const seconds = useElapsed(startedAt);
  return (
    <section
      aria-label="Teach-back"
      className="rounded-2xl border border-bloom/40 bg-bloom/10 p-4"
      data-testid="teach-back"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-bloom">You are the teacher now</p>
        <span className="font-mono text-xs text-foreground/60" aria-label="Time teaching">
          {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
        </span>
      </div>
      <p className="mt-1 text-sm text-foreground/80">
        Drona is a confused first-year student. Explain it in your own words and correct their
        mix-ups. They will not tell you whether you are right until you finish.
      </p>
      {heard && (
        <p className="mt-2 line-clamp-3 rounded-lg bg-night/50 px-3 py-2 text-sm text-foreground/80">
          “{heard}”
        </p>
      )}
      <button
        type="button"
        onClick={onDone}
        disabled={disabled}
        className="mt-3 rounded-lg bg-bloom/20 px-3 py-1.5 text-sm text-bloom outline-none hover:bg-bloom/30 focus-visible:ring-2 focus-visible:ring-bloom disabled:opacity-40"
      >
        I&apos;m done explaining
      </button>
    </section>
  );
}

export function Captions({ agent, user }: { agent: string; user: string }) {
  return (
    <div
      className="glass min-h-24 rounded-2xl p-4 text-sm leading-relaxed"
      role="log"
      aria-live="polite"
      aria-label="Live captions"
    >
      {agent ? (
        <p>
          <span className="mr-2 text-xs uppercase tracking-widest text-glow">Drona</span>
          {agent}
        </p>
      ) : (
        <p className="text-foreground/50">Captions appear here as Drona speaks.</p>
      )}
      {user && (
        <p className="mt-2 text-foreground/70">
          <span className="mr-2 text-xs uppercase tracking-widest text-moss">You</span>
          {user}
        </p>
      )}
    </div>
  );
}

const KIND_COPY: Record<TickerEntry["kind"], { label: string; tone: string }> = {
  provisional: { label: "Growing (provisional)", tone: "text-glow" },
  confirmed: { label: "Confirmed", tone: "text-moss" },
  retracted: { label: "Adjusted", tone: "text-ember" },
  noted: { label: "Noted", tone: "text-foreground/60" },
};

/** Provisional evidence ticker. Glowing growth is a preview; the post-call judge settles it. */
export function EvidenceTicker({ entries }: { entries: TickerEntry[] }) {
  return (
    <section aria-label="Evidence ticker" className="glass rounded-2xl p-4">
      <h2 className="text-[0.7rem] font-medium uppercase tracking-[0.22em] text-foreground/60">
        Evidence so far
      </h2>
      {entries.length === 0 ? (
        <p className="mt-2 text-sm text-foreground/50">
          Answer a question and your plant will start to glow. Growth stays provisional until the
          session ends and is checked.
        </p>
      ) : (
        <ul className="mt-2 flex flex-col gap-2" aria-live="polite">
          {entries.map((t) => (
            <li key={t.id} className="rounded-xl bg-white/5 px-3 py-2 text-sm">
              <p className="flex flex-wrap items-baseline gap-x-2">
                <span className={`text-xs font-medium ${KIND_COPY[t.kind].tone}`}>
                  {KIND_COPY[t.kind].label}
                </span>
                <span className="font-mono text-xs text-foreground/70">{t.conceptId}</span>
                {t.part && (
                  <span className="text-xs text-foreground/60">
                    {PART_LABEL[t.part]}
                    {t.assisted ? " · assisted" : ""}
                  </span>
                )}
              </p>
              {t.quote && t.kind !== "retracted" && (
                <p className="mt-1 line-clamp-2 text-foreground/70">“{t.quote}”</p>
              )}
              {t.reason && <p className="mt-1 text-foreground/70">{t.reason}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function EditorPlaceholder({
  problemId,
  language,
  onClose,
}: {
  problemId: string;
  language: string;
  onClose: () => void;
}) {
  return (
    <section className="glass rounded-2xl p-4 text-sm" aria-label="Code editor">
      <div className="flex items-start justify-between gap-3">
        <p>
          Drona opened the editor for <span className="font-mono">{problemId}</span> ({language}).
        </p>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg px-2 py-1 text-xs text-foreground/60 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-glow"
        >
          Close
        </button>
      </div>
      <p className="mt-1 text-foreground/60">
        The Monaco editor with test runs arrives with the Arjuna interview (C16).
      </p>
    </section>
  );
}

export function DiagramPlaceholder({
  id,
  caption,
  onClose,
}: {
  id: string;
  caption: string;
  onClose: () => void;
}) {
  return (
    <figure className="glass rounded-2xl p-4 text-sm" aria-label="Diagram">
      <div className="grid h-28 place-items-center rounded-xl border border-dashed border-white/15 font-mono text-xs text-foreground/50">
        diagram {id}
      </div>
      {caption && <figcaption className="mt-2 text-foreground/80">{caption}</figcaption>}
      <button
        type="button"
        onClick={onClose}
        className="mt-2 rounded-lg px-2 py-1 text-xs text-foreground/60 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-glow"
      >
        Close
      </button>
    </figure>
  );
}
