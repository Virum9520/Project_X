"use client";

import type { AssistantAnswer, AssistantTurn } from "@sg/contracts";
import { useRef, useState, useTransition } from "react";

import { Badge } from "@/components/ui";
import { usd } from "@/lib/format";

import { askAssistant } from "./actions";

type Entry =
  | { kind: "question"; text: string }
  | { kind: "answer"; answer: AssistantAnswer }
  | { kind: "error"; message: string };

const EXAMPLES = [
  "Which component costs the most per completed session this month?",
  "Are any cost centers on track to exceed their monthly budget?",
  "How did call outcomes change over the last 14 days?",
];

/**
 * Conversation with the owner assistant. The transcript lives only in this page (nothing is
 * stored); the last turns are sent back as context. Answers render as plain text, never as HTML,
 * because they are model output built from data we do not control.
 */
export function AskBox({ disabled, reason }: { disabled: boolean; reason: string | null }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [question, setQuestion] = useState("");
  const [pending, startTransition] = useTransition();
  const turns = useRef<AssistantTurn[]>([]);

  function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || pending || disabled) return;
    setEntries((all) => [...all, { kind: "question", text: trimmed }]);
    setQuestion("");
    const history = [...turns.current];
    startTransition(async () => {
      const result = await askAssistant(trimmed, history);
      if (result.status === "ok") {
        turns.current = [
          ...history,
          { role: "user" as const, content: trimmed },
          { role: "assistant" as const, content: result.answer.answer.slice(0, 4000) },
        ].slice(-12);
        setEntries((all) => [...all, { kind: "answer", answer: result.answer }]);
      } else {
        setEntries((all) => [...all, { kind: "error", message: result.message }]);
      }
    });
  }

  return (
    <div className="space-y-4">
      {disabled && (
        <p className="rounded-lg border border-ember/30 bg-ember/5 p-3 text-sm text-ember">
          {reason}
        </p>
      )}
      <ol className="space-y-4" aria-live="polite">
        {entries.map((entry, i) => (
          <li key={i}>
            {entry.kind === "question" && (
              <p className="ml-auto max-w-2xl rounded-xl bg-white/5 px-4 py-2 text-sm">
                {entry.text}
              </p>
            )}
            {entry.kind === "error" && (
              <p
                role="alert"
                className="rounded-lg border border-bloom/30 bg-bloom/5 p-3 text-sm text-bloom"
              >
                {entry.message}
              </p>
            )}
            {entry.kind === "answer" && <AnswerView answer={entry.answer} />}
          </li>
        ))}
        {pending && <li className="text-sm text-foreground/50">Working on it...</li>}
      </ol>

      {entries.length === 0 && !disabled && (
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => submit(example)}
              className="rounded-full border border-white/15 px-3 py-1 text-xs text-foreground/70 hover:bg-white/5"
            >
              {example}
            </button>
          ))}
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(question);
        }}
        className="flex gap-2"
      >
        <label className="sr-only" htmlFor="assistant-question">
          Question
        </label>
        <textarea
          id="assistant-question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit(question);
            }
          }}
          maxLength={2000}
          rows={2}
          disabled={disabled}
          placeholder="Ask about usage, cost, calls or quality"
          className="block w-full resize-y rounded-lg border border-white/15 bg-night px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={pending || disabled || !question.trim()}
          className="self-end rounded-lg bg-moss px-4 py-2 text-sm font-medium text-night disabled:opacity-40"
        >
          Ask
        </button>
      </form>
    </div>
  );
}

function AnswerView({ answer }: { answer: AssistantAnswer }) {
  const unavailable = Object.entries(answer.unavailable_providers);
  return (
    <article className="space-y-3 rounded-xl border border-white/10 bg-dusk/60 p-4">
      <div className="flex flex-wrap items-center gap-2">
        {answer.partial && <Badge tone="warn">partial answer</Badge>}
        {answer.stopped && <Badge tone="bad">stopped: {answer.stopped.replaceAll("_", " ")}</Badge>}
        {answer.basis && <Badge tone="neutral">amounts: {answer.basis.amounts}</Badge>}
      </div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed">{answer.answer}</p>

      {answer.hypotheses.length > 0 && (
        <div>
          <h3 className="text-xs uppercase tracking-wider text-ember">Hypotheses, not findings</h3>
          <ul className="mt-1 list-inside list-disc text-sm text-foreground/70">
            {answer.hypotheses.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </div>
      )}

      {answer.warnings.map((w) => (
        <p key={w} className="text-xs text-ember">
          {w}
        </p>
      ))}
      {unavailable.length > 0 && (
        <p className="text-xs text-foreground/60">
          Not available: {unavailable.map(([p, why]) => `${p} (${why})`).join("; ")}
        </p>
      )}

      <details className="text-xs text-foreground/60">
        <summary className="cursor-pointer select-none">Basis and tool calls</summary>
        {answer.basis ? (
          <dl className="mt-2 grid gap-1 sm:grid-cols-[8rem_1fr]">
            <dt>Date range</dt>
            <dd>{answer.basis.date_range || "not stated"}</dd>
            <dt>Metrics</dt>
            <dd>{answer.basis.metrics.join("; ") || "not stated"}</dd>
            <dt>Filters</dt>
            <dd>{answer.basis.filters.join("; ") || "none"}</dd>
            <dt>Freshness</dt>
            <dd>{answer.basis.freshness || "not stated"}</dd>
          </dl>
        ) : (
          <p className="mt-2 text-ember">
            This answer did not state its basis. Treat it with care.
          </p>
        )}
        <ul className="mt-2 space-y-1">
          {answer.tools.map((t, i) => (
            <li key={i} className="tabular-nums">
              {t.ok ? "ok" : "failed"} · {t.tool}
              {t.rows !== null ? ` · ${t.rows} rows` : ""}
              {t.truncated ? " · truncated" : ""} · {t.duration_ms} ms
              {t.error ? ` · ${t.error}` : ""}
            </li>
          ))}
          {answer.tools.length === 0 && <li>No tools were called.</li>}
        </ul>
        <p className="mt-2 tabular-nums">
          {answer.model ?? "model unknown"} · {answer.steps} steps · {usd(answer.cost_usd, 4)} ·
          request {answer.request_id}
        </p>
      </details>
    </article>
  );
}
