"use client";

import type { EditorLanguage, ProblemView, RunExamplesResult } from "@sg/contracts";
import { useState } from "react";

import { Workbench, type ExamplesOutcome } from "@/components/arjuna/workbench";

const STARTER: Record<string, string> = {
  javascript:
    "function twoSum(nums, target) {\n  // return the indices of the two numbers that add up to target\n}\n",
  python:
    "def two_sum(nums, target):\n    # return the indices of the two numbers that add up to target\n    pass\n",
};

const problem: ProblemView = {
  id: "demo.two-sum",
  title: "Two Sum",
  statement:
    "Given an array of integers `nums` and an integer `target`, return the indices of the two numbers that add up to `target`. Exactly one solution exists; do not use the same element twice.",
  difficulty: 1,
  concept_id: "arrays.hash-maps",
  function: "twoSum",
  params: ["nums", "target"],
  language: "javascript",
  starter_code: STARTER.javascript,
  examples: [
    { label: "basic", input: { nums: [2, 7, 11, 15], target: 9 }, expected: [0, 1] },
    { label: "middle", input: { nums: [3, 2, 4], target: 6 }, expected: [1, 2] },
    { label: "duplicates", input: { nums: [3, 3], target: 6 }, expected: [0, 1] },
  ],
  tests_available: true,
  runnable_languages: ["javascript"],
};

/** Static demo: examples run in this browser tab only (JavaScript); the real app uses a sandbox. */
function runExamples(code: string): ExamplesOutcome {
  let fn: (...a: unknown[]) => unknown;
  try {
    fn = new Function(`${code}\nreturn twoSum;`)() as typeof fn;
  } catch (e) {
    return { ok: false, message: `Your code did not compile: ${String(e)}` };
  }
  const results = problem.examples.map((ex) => {
    let actual: string | null = null;
    let detail: string | null = null;
    try {
      const out = fn(...problem.params.map((p) => ex.input[p]));
      actual = JSON.stringify(out);
    } catch (e) {
      detail = String(e);
    }
    const passed = actual !== null && actual === JSON.stringify(ex.expected);
    return { label: ex.label, passed, input: ex.input, expected: ex.expected, actual, detail };
  });
  const passed = results.filter((r) => r.passed).length;
  const data: RunExamplesResult = {
    status: passed === results.length ? "passed" : "failed",
    passed,
    total: results.length,
    summary: `${passed} of ${results.length} examples passed.`,
    results,
  };
  return { ok: true, data };
}

export default function TechnicalInterviewDemo() {
  const [language, setLanguage] = useState<EditorLanguage>("javascript");
  return (
    <main className="mx-auto w-full max-w-4xl flex-1 px-4 pb-16 pt-28">
      <p className="mb-4 rounded-xl bg-ember/10 px-3 py-2 text-sm text-ember" role="note">
        Static demo of Arjuna&apos;s coding panel. The voice interview, hidden tests and sandbox run
        in the full app.
      </p>
      <Workbench
        problem={problem}
        language={language}
        initialCode={STARTER.javascript}
        runs={[]}
        canRun
        onCodeChange={() => {}}
        onLanguageChange={setLanguage}
        onRunExamples={async (code) =>
          language === "javascript"
            ? runExamples(code)
            : { ok: false, message: "The static demo runs JavaScript only." }
        }
      />
    </main>
  );
}
