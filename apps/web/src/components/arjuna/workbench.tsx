"use client";

import type {
  AgentRun,
  EditorLanguage,
  ProblemView,
  RunExamplesResult,
  RunnableLanguage,
} from "@sg/contracts";
import { RUNNABLE_LANGUAGES } from "@sg/contracts";
import { loader } from "@monaco-editor/react";
import dynamic from "next/dynamic";
import { useState } from "react";

import { describeRun } from "@/lib/arjuna/runs";

// Serve Monaco from /monaco (copied by scripts/copy-monaco.mjs), not the jsDelivr default.
loader.config({ paths: { vs: `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/monaco/vs` } });

/** Monaco is large and browser-only: load it on demand, never on the server. */
const MonacoEditor = dynamic(() => import("@monaco-editor/react").then((m) => m.default), {
  ssr: false,
  loading: () => (
    <div className="grid h-full place-items-center text-sm text-foreground/50">Loading editor…</div>
  ),
});

const LANGUAGE_LABEL: Record<EditorLanguage, string> = {
  python: "Python",
  javascript: "JavaScript",
  typescript: "TypeScript",
  java: "Java",
  cpp: "C++",
  go: "Go",
};

const isRunnable = (l: EditorLanguage): l is RunnableLanguage =>
  (RUNNABLE_LANGUAGES as readonly string[]).includes(l);

export type ExamplesOutcome =
  { ok: true; data: RunExamplesResult } | { ok: false; message: string };

export interface WorkbenchProps {
  problem: ProblemView;
  language: EditorLanguage;
  initialCode: string;
  /** Agent test runs for this problem, oldest first. */
  runs: AgentRun[];
  /** False before the call starts or after it ends: running practice examples needs a session. */
  canRun: boolean;
  onCodeChange: (code: string) => void;
  onLanguageChange: (language: RunnableLanguage) => void;
  onRunExamples: (code: string) => Promise<ExamplesOutcome>;
  onClose?: () => void;
}

/**
 * The coding panel: problem statement, Monaco editor, practice runs against the public examples,
 * and the results of the tests Arjuna ran. Hidden tests are never shown: for a failing hidden
 * case the panel only has its label (see `AgentRun.first_failure`).
 */
export function Workbench({
  problem,
  language,
  initialCode,
  runs,
  canRun,
  onCodeChange,
  onLanguageChange,
  onRunExamples,
  onClose,
}: WorkbenchProps) {
  const [code, setCode] = useState(initialCode);
  const [busy, setBusy] = useState(false);
  const [examples, setExamples] = useState<ExamplesOutcome | null>(null);
  const latest = runs.length ? runs[runs.length - 1] : null;
  const runnable = isRunnable(language);

  async function runPractice() {
    setBusy(true);
    setExamples(null);
    setExamples(await onRunExamples(code));
    setBusy(false);
  }

  return (
    <section aria-label="Code editor" className="glass flex flex-col gap-3 rounded-2xl p-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[0.7rem] uppercase tracking-[0.22em] text-glow">
            Coding problem · {"●".repeat(problem.difficulty)}
            <span className="sr-only"> difficulty {problem.difficulty} of 3</span>
          </p>
          <h2 className="mt-1 text-lg font-semibold">{problem.title}</h2>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-foreground/70">
            Language
            <select
              value={isRunnable(language) ? language : "python"}
              onChange={(e) => onLanguageChange(e.target.value as RunnableLanguage)}
              className="rounded-lg border border-white/15 bg-night px-2 py-1 text-sm outline-none focus-visible:ring-2 focus-visible:ring-glow"
            >
              {RUNNABLE_LANGUAGES.map((l) => (
                <option key={l} value={l}>
                  {LANGUAGE_LABEL[l]}
                </option>
              ))}
            </select>
          </label>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-2 py-1 text-xs text-foreground/60 outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-glow"
            >
              Close
            </button>
          )}
        </div>
      </header>

      <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
        {problem.statement}
      </p>
      {problem.examples.length > 0 && (
        <ul className="grid gap-2 sm:grid-cols-2" aria-label="Examples">
          {problem.examples.map((e) => (
            <li key={e.label} className="rounded-xl bg-night/60 p-3 font-mono text-xs">
              <p className="mb-1 font-sans text-[0.7rem] uppercase tracking-widest text-foreground/50">
                {e.label}
              </p>
              <pre className="whitespace-pre-wrap break-words">
                {Object.entries(e.input)
                  .map(([k, v]) => `${k} = ${JSON.stringify(v)}`)
                  .join("\n")}
              </pre>
              <p className="mt-1 text-moss">→ {JSON.stringify(e.expected)}</p>
            </li>
          ))}
        </ul>
      )}

      {!problem.tests_available && (
        <p role="status" className="rounded-xl bg-ember/10 px-3 py-2 text-sm text-ember">
          Tests only run for Python, JavaScript and TypeScript. Switch the language to have Arjuna
          run them, or talk the code through with him.
        </p>
      )}

      <div
        className="h-80 overflow-hidden rounded-xl border border-white/10"
        data-testid="code-editor"
      >
        <MonacoEditor
          height="100%"
          theme="vs-dark"
          language={language}
          value={code}
          onChange={(value) => {
            const next = value ?? "";
            setCode(next);
            onCodeChange(next);
          }}
          options={{
            minimap: { enabled: false },
            fontSize: 14,
            tabSize: language === "python" ? 4 : 2,
            scrollBeyondLastLine: false,
            automaticLayout: true,
            ariaLabel: `Code for ${problem.title}`,
            wordWrap: "on",
          }}
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={runPractice}
          disabled={busy || !canRun || !runnable || !code.trim()}
          className="rounded-xl border border-white/15 px-4 py-2 text-sm outline-none hover:border-white/30 focus-visible:ring-2 focus-visible:ring-glow disabled:opacity-40"
        >
          {busy ? "Running…" : "Run examples"}
        </button>
        <p className="text-xs text-foreground/60">
          Practice only. Say “run the tests” when you are ready and Arjuna will run the full set.
        </p>
      </div>

      {examples && <ExampleResults outcome={examples} />}
      {latest && <AgentRunSummary run={latest} history={runs.length} />}
    </section>
  );
}

function ExampleResults({ outcome }: { outcome: ExamplesOutcome }) {
  if (!outcome.ok)
    return (
      <p role="alert" className="rounded-xl bg-ember/10 px-3 py-2 text-sm text-ember">
        {outcome.message}
      </p>
    );
  const { results, summary } = outcome.data;
  return (
    <div aria-live="polite" className="rounded-xl bg-white/5 p-3 text-sm">
      <p className="font-medium">{summary}</p>
      <ul className="mt-2 flex flex-col gap-1.5">
        {results.map((r) => (
          <li key={r.label} className="font-mono text-xs">
            <span className={r.passed ? "text-moss" : "text-ember"}>
              {r.passed ? "✓" : "✗"} {r.label}
            </span>
            {!r.passed && (
              <span className="ml-2 text-foreground/70">
                {r.detail ??
                  (r.actual ? `got ${r.actual}, expected ${JSON.stringify(r.expected)}` : "")}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** What Arjuna's last test run found. Counts and the failing case's label, nothing more. */
export function AgentRunSummary({ run, history }: { run: AgentRun; history: number }) {
  const d = describeRun(run);
  return (
    <div
      aria-live="polite"
      className="rounded-xl border border-white/10 bg-night/50 p-3 text-sm"
      data-testid="agent-run"
    >
      <p className="text-[0.7rem] uppercase tracking-[0.22em] text-foreground/50">
        Arjuna ran the tests{history > 1 ? ` · run ${history}` : ""}
      </p>
      <p className={`mt-1 font-medium ${d.tone}`}>{d.headline}</p>
      {d.detail && <p className="mt-0.5 text-foreground/70">{d.detail}</p>}
    </div>
  );
}
