"use client";

import type { AskSanjayaAnswer, FocusTarget, GardenDataset } from "@sg/contracts";
import { useState, useTransition } from "react";

import { askSanjaya } from "@/app/(app)/garden/actions";

import { Panel } from "./primitives";

const SUGGESTIONS = [
  "How ready am I for interviews?",
  "What should I focus on next?",
  "What changed this week and why?",
  "Which reviews are overdue?",
];

/**
 * Ask Sanjaya: plain-language questions about your own garden. Answers come from the same numbers
 * the dashboard shows and cite evidence; each citation jumps to its plant. When the model is not
 * available the answer is composed from those numbers without it, and says so.
 */
export function AskSanjaya({
  dataset,
  live,
  onFocus,
}: {
  dataset: GardenDataset;
  live: boolean;
  onFocus: (target: FocusTarget) => void;
}) {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [answer, setAnswer] = useState<AskSanjayaAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const evidenceById = new Map(dataset.evidence.map((e) => [e.id, e]));
  const titleOf = new Map(dataset.plants.map((p) => [p.key, p.title]));

  const ask = (text: string) => {
    const q = text.trim();
    if (!q || pending) return;
    setError(null);
    setAsked(q);
    startTransition(async () => {
      const result = await askSanjaya(q);
      if (result.ok) setAnswer(result.data);
      else {
        setAnswer(null);
        setError(result.message);
      }
    });
  };

  const cited = (answer?.citations ?? [])
    .map((id) => evidenceById.get(id))
    .filter((e) => e !== undefined);

  return (
    <Panel id="ask-sanjaya" title="Ask Sanjaya">
      {!live ? (
        <p className="text-sm text-foreground/60">
          Sanjaya answers from your real garden, so he is off while sample data is showing.
        </p>
      ) : (
        <>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              ask(question);
            }}
            className="flex gap-2"
          >
            <label htmlFor="ask-sanjaya-input" className="sr-only">
              Ask Sanjaya about your garden
            </label>
            <input
              id="ask-sanjaya-input"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={500}
              placeholder="Why is Graphs still assisted?"
              className="min-w-0 flex-1 rounded-lg border border-white/15 bg-night/70 px-3 py-2 text-sm outline-none focus-visible:border-glow focus-visible:ring-2 focus-visible:ring-glow/40"
            />
            <button
              type="submit"
              disabled={pending || !question.trim()}
              className="rounded-lg bg-moss px-3 py-2 text-sm font-medium text-night outline-none focus-visible:ring-2 focus-visible:ring-glow disabled:opacity-60"
            >
              {pending ? "Thinking…" : "Ask"}
            </button>
          </form>
          <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Suggested questions">
            {SUGGESTIONS.map((s) => (
              <li key={s}>
                <button
                  type="button"
                  disabled={pending}
                  onClick={() => {
                    setQuestion(s);
                    ask(s);
                  }}
                  className="rounded-full bg-white/5 px-2.5 py-1 text-xs text-foreground/80 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-glow/60 disabled:opacity-60"
                >
                  {s}
                </button>
              </li>
            ))}
          </ul>
          <div aria-live="polite" className="mt-3 text-sm">
            {error && (
              <p role="alert" className="rounded-lg bg-ember/15 px-3 py-2 text-xs text-ember">
                {error}
              </p>
            )}
            {answer && asked && (
              <div className="space-y-2">
                <p className="text-xs text-foreground/50">You asked: {asked}</p>
                <p className="whitespace-pre-wrap">{answer.answer}</p>
                {!answer.grounded && (
                  <p className="text-xs text-foreground/50">
                    Sanjaya&apos;s voice is unavailable, so this is just your numbers.
                  </p>
                )}
                {cited.length > 0 && (
                  <p className="flex flex-wrap items-center gap-1.5 text-[0.7rem]">
                    <span className="text-foreground/40">Evidence:</span>
                    {cited.map((e) => (
                      <button
                        key={e.id}
                        type="button"
                        onClick={() => onFocus({ level: "plant", plantKey: e.plantKey })}
                        className="rounded-full bg-white/5 px-2 py-0.5 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-glow/60"
                      >
                        {titleOf.get(e.plantKey) ?? e.plantKey} · {e.dimension}
                      </button>
                    ))}
                  </p>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </Panel>
  );
}
