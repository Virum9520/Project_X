"use client";

import type { AgentRun, ExampleResult, RunnableLanguage } from "@sg/contracts";
import { useCallback, useRef, useState } from "react";

import { Workbench, type ExamplesOutcome } from "@/components/arjuna/workbench";
import { loadCases, type BankProblem, type ProblemCase } from "@/lib/practice/bank";
import type { EvidenceDraft } from "@/lib/practice/dataset";
import { toProblemView } from "@/lib/practice/problems";
import { runCases, warmPython, type CaseOutcome } from "@/lib/practice/runner";
import { wordCount } from "@/lib/practice/scoring";

/**
 * One coding problem in an interview: the editor, practice runs on the public examples, the
 * full test run (hidden cases included, reported by count and the first failing label only),
 * hints (which make the evidence assisted), and the evidence the attempt earns.
 */

interface Attempt {
  problem: BankProblem;
  /** The live draft, in the language currently selected. */
  language: RunnableLanguage;
  code: string;
  hints: number;
  /** The best full run, with the code and language that produced it. */
  best: AgentRun | null;
  bestCode: string;
  bestLanguage: RunnableLanguage;
  complexity: string | null;
}

const LANGUAGE_NAME: Record<RunnableLanguage, string> = {
  python: "Python",
  javascript: "JavaScript",
  typescript: "TypeScript",
};

const publicCases = (problem: BankProblem): ProblemCase[] =>
  problem.examples.map((e) => ({
    label: e.label,
    args: problem.params.map((p) => e.input[p]),
    expected: e.expected,
    public: true,
  }));

function excerpt(code: string): string {
  const lines = code
    .split("\n")
    .map((l) => l.replace(/\s+$/, ""))
    .filter((l) => l.trim() && !/^\s*(#|\/\/|"""|''')/.test(l));
  return lines.slice(0, 6).join("\n");
}

function summarise(outcomes: CaseOutcome[]): Pick<
  AgentRun,
  "status" | "passed" | "total" | "summary" | "first_failure"
> & {
  detail: string | null;
} {
  const passed = outcomes.filter((o) => o.status === "pass").length;
  const total = outcomes.length;
  const first = outcomes.find((o) => o.status !== "pass") ?? null;
  const status: AgentRun["status"] = !first
    ? "passed"
    : first.status === "fail"
      ? "failed"
      : first.status === "error"
        ? "error"
        : "timeout";
  return {
    status,
    passed,
    total,
    summary: `Passed ${passed} of ${total} tests.`,
    first_failure: first ? first.label : null,
    detail: first?.detail ?? null,
  };
}

function attemptIn(
  attempts: Map<string, Attempt>,
  p: BankProblem,
  lang: RunnableLanguage,
): Attempt {
  let a = attempts.get(p.id);
  if (!a) {
    a = {
      problem: p,
      language: lang,
      code: p.starter[lang],
      bestCode: "",
      bestLanguage: lang,
      hints: 0,
      best: null,
      complexity: null,
    };
    attempts.set(p.id, a);
  }
  return a;
}

const SPACE = /\b(space|memory|extra|auxiliary|in place|in-place)\b/i;
const COMPLEXITY =
  /\bo\s*\(|\b(constant|linear|logarithmic|log\s*n|n\s*log\s*n|quadratic|cubic|exponential|n\s*squared)\b/i;

export function useCodingRound({
  say,
  onRun,
}: {
  /** Arjuna speaks (and the transcript records it). */
  say: (text: string) => Promise<void>;
  /** Called with every full test run, before Arjuna reports it. */
  onRun?: (run: AgentRun, problem: BankProblem) => void;
}) {
  const [problem, setProblem] = useState<BankProblem | null>(null);
  const [language, setLanguage] = useState<RunnableLanguage>("python");
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [askedComplexity, setAskedComplexity] = useState(false);
  const [initialCode, setInitialCode] = useState("");
  const drafts = useRef(new Map<string, string>());
  const attempts = useRef(new Map<string, Attempt>());
  const current = useRef<{ problem: BankProblem | null; language: RunnableLanguage }>({
    problem: null,
    language: "python",
  });

  const warm = useCallback((lang: RunnableLanguage) => {
    if (lang !== "python") return;
    setStatus("Loading Python in your browser…");
    warmPython().then(
      () => setStatus(null),
      (e: unknown) => setStatus(e instanceof Error ? e.message : "Python could not load."),
    );
  }, []);

  const open = useCallback(
    (next: BankProblem, lang: RunnableLanguage) => {
      current.current = { problem: next, language: lang };
      attemptIn(attempts.current, next, lang);
      setInitialCode(drafts.current.get(`${next.id}:${lang}`) ?? next.starter[lang]);
      setProblem(next);
      setLanguage(lang);
      setAskedComplexity(false);
      warm(lang);
    },
    [warm],
  );

  const changeLanguage = useCallback(
    (lang: RunnableLanguage) => {
      const p = current.current.problem;
      current.current = { ...current.current, language: lang };
      if (p) setInitialCode(drafts.current.get(`${p.id}:${lang}`) ?? p.starter[lang]);
      setLanguage(lang);
      warm(lang);
    },
    [warm],
  );

  const draftKey = problem ? `${problem.id}:${language}` : "";

  const onCodeChange = useCallback(
    (code: string) => {
      drafts.current.set(draftKey, code);
      const p = current.current.problem;
      if (p) {
        const a = attemptIn(attempts.current, p, current.current.language);
        a.code = code;
        a.language = current.current.language;
      }
    },
    [draftKey],
  );

  const runExamples = useCallback(async (code: string): Promise<ExamplesOutcome> => {
    const p = current.current.problem;
    if (!p) return { ok: false, message: "No problem is open." };
    const lang = current.current.language;
    const view = toProblemView(p, lang);
    const cases = publicCases(p);
    const outcomes = await runCases({
      language: lang,
      code,
      fn: view.function,
      cases,
      timeLimitS: p.time_limit_s,
      onStatus: setStatus,
    });
    setStatus(null);
    const results: ExampleResult[] = outcomes.map((o, i) => ({
      label: o.label,
      passed: o.status === "pass",
      input: p.examples[i]?.input ?? {},
      expected: p.examples[i]?.expected ?? null,
      actual: o.actual,
      detail:
        o.status === "timeout"
          ? "Ran out of time."
          : o.status === "skipped"
            ? "Not run: an earlier example ran out of time."
            : o.detail,
    }));
    const passed = results.filter((r) => r.passed).length;
    return {
      ok: true,
      data: {
        status: passed === results.length ? "passed" : "failed",
        passed,
        total: results.length,
        summary: `${passed} of ${results.length} examples passed.`,
        results,
      },
    };
  }, []);

  /** Run every case, hidden ones included. Resolves with the run once Arjuna has reported it. */
  const runTests = useCallback(async (): Promise<AgentRun | null> => {
    const p = current.current.problem;
    if (!p || testing) return null;
    const lang = current.current.language;
    const a = attemptIn(attempts.current, p, lang);
    const code = drafts.current.get(`${p.id}:${lang}`) ?? a.code;
    if (!code.trim() || code === p.starter[lang]) {
      await say("Write some code first, then I'll run the tests.");
      return null;
    }
    setTesting(true);
    try {
      setStatus("Loading the tests…");
      let cases: ProblemCase[];
      try {
        cases = await loadCases(p.id);
      } catch {
        setStatus(null);
        await say("I couldn't load the tests just now. Check your connection and try again.");
        return null;
      }
      const outcomes = await runCases({
        language: lang,
        code,
        fn: toProblemView(p, lang).function,
        cases,
        timeLimitS: p.time_limit_s,
        onStatus: setStatus,
      });
      setStatus(null);
      const s = summarise(outcomes);
      const run: AgentRun = {
        id: `run_${Date.now().toString(36)}`,
        problem_id: p.id,
        status: s.status,
        passed: s.passed,
        total: s.total,
        summary: s.summary,
        first_failure: s.first_failure,
        assisted: a.hints > 0,
        at: new Date().toISOString(),
      };
      setRuns((prev) => [...prev, run]);
      onRun?.(run, p);
      if (!a.best || run.passed > a.best.passed || run.status === "passed") {
        a.best = run;
        a.bestCode = code;
        a.bestLanguage = lang;
      }
      if (run.status === "passed") {
        setAskedComplexity(true);
        await say(
          `All ${run.total} tests pass, including the hidden ones.${
            run.assisted ? " You had a hint on this one, so it counts as assisted." : ""
          } What's the time and space complexity of your solution?`,
        );
      } else if (run.status === "timeout") {
        await say(
          `${run.passed} of ${run.total} pass, then it ran out of time on "${run.first_failure}". Think about the complexity: can you avoid repeated work?`,
        );
      } else if (run.status === "error") {
        const kind = s.detail?.split(":")[0] ?? "an error";
        await say(
          `${run.passed} of ${run.total} pass. On "${run.first_failure}" the code raised ${kind}. Take another look.`,
        );
      } else {
        await say(
          `${run.passed} of ${run.total} pass. The first failing case is "${run.first_failure}". Want to take another look?`,
        );
      }
      return run;
    } finally {
      setTesting(false);
      setStatus(null);
    }
  }, [say, onRun, testing]);

  const hint = useCallback(async () => {
    const p = current.current.problem;
    if (!p) return;
    const a = attemptIn(attempts.current, p, current.current.language);
    if (a.hints >= p.hints.length) {
      await say("That's all my hints. Talk me through what you have so far.");
      return;
    }
    const text = p.hints[a.hints]!;
    a.hints += 1;
    await say(`Here's a hint. ${text}`);
  }, [say]);

  /** The learner answered the complexity question: Arjuna's reply, and whether it earns credit. */
  const answerComplexity = useCallback(
    (answer: string): { reply: string; outcome: "demonstrated" | "partial" | null } => {
      const p = current.current.problem;
      setAskedComplexity(false);
      if (!p) return { reply: "Thanks.", outcome: null };
      const a = attemptIn(attempts.current, p, current.current.language);
      const time = COMPLEXITY.test(answer);
      const space = SPACE.test(answer);
      if (time && (space || wordCount(answer) >= 12)) {
        a.complexity = answer;
        return {
          reply:
            "Good, that's the analysis I wanted. Check it against your loops before you move on.",
          outcome: space ? "demonstrated" : "partial",
        };
      }
      if (time) {
        a.complexity = answer;
        return {
          reply: "And the space? Think about what extra structures you keep.",
          outcome: "partial",
        };
      }
      return {
        reply: "Try to say it in Big-O terms: how does the work grow as the input grows?",
        outcome: null,
      };
    },
    [],
  );

  /** Evidence from every problem attempted: application from the tests, explanation from the
   * complexity answer. Assisted when Arjuna gave a hint on that problem. */
  const evidence = useCallback((): EvidenceDraft[] => {
    const out: EvidenceDraft[] = [];
    for (const a of attempts.current.values()) {
      const run = a.best;
      if (!run) continue;
      const kind = a.hints > 0 ? "assisted" : "independent";
      const share = run.total ? run.passed / run.total : 0;
      if (run.status === "passed" || share >= 0.5) {
        out.push({
          plantKey: a.problem.concept_id,
          dimension: "application",
          kind,
          outcome: run.status === "passed" ? "demonstrated" : "partial",
          quote: excerpt(a.bestCode),
          source: "tests",
          rationale: `${a.problem.title} in ${LANGUAGE_NAME[a.bestLanguage]}: passed ${run.passed} of ${run.total} tests, hidden cases included.`,
          assistNote:
            kind === "assisted"
              ? `Solved after ${a.hints} ${a.hints === 1 ? "hint" : "hints"} from Arjuna.`
              : undefined,
          confidence: run.status === "passed" ? 0.9 : 0.75,
        });
      }
      if (a.complexity && run.status === "passed") {
        out.push({
          plantKey: a.problem.concept_id,
          dimension: "explanation",
          kind,
          outcome: SPACE.test(a.complexity) ? "demonstrated" : "partial",
          quote: a.complexity,
          source: "transcript",
          rationale: `Explained the time and space cost of a passing ${a.problem.title} solution.`,
          assistNote: kind === "assisted" ? "The solution came after a hint." : undefined,
          confidence: 0.7,
        });
      }
    }
    return out;
  }, []);

  const attempted = useCallback(() => [...attempts.current.values()], []);

  const reset = useCallback(() => {
    attempts.current.clear();
    drafts.current.clear();
    current.current = { problem: null, language: current.current.language };
    setProblem(null);
    setRuns([]);
    setStatus(null);
    setAskedComplexity(false);
  }, []);

  const workbench = problem ? (
    <Workbench
      key={draftKey}
      problem={toProblemView(problem, language)}
      language={language}
      initialCode={initialCode}
      runs={runs.filter((r) => r.problem_id === problem.id)}
      canRun
      onCodeChange={onCodeChange}
      onLanguageChange={changeLanguage}
      onRunExamples={runExamples}
      actions={
        <button
          type="button"
          onClick={() => void runTests()}
          disabled={testing}
          className="rounded-xl bg-moss px-4 py-2 text-sm font-medium text-night outline-none hover:brightness-110 focus-visible:ring-2 focus-visible:ring-glow disabled:opacity-50"
        >
          {testing ? "Running the tests…" : "Run all tests"}
        </button>
      }
      note={
        status ??
        `Examples are practice. “Run all tests” checks ${problem.hidden_count} hidden cases too; you can also say “run the tests”.`
      }
    />
  ) : null;

  return {
    problem,
    language,
    setLanguage: changeLanguage,
    open,
    runTests,
    hint,
    answerComplexity,
    askedComplexity,
    evidence,
    attempted,
    reset,
    testing,
    workbench,
  };
}
