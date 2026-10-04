"use client";

import type { AgentRun, ArjunaPlan, ProblemView } from "@sg/contracts";
import { useState } from "react";

import { PlanCard } from "@/components/arjuna/plan-card";
import { Workbench } from "@/components/arjuna/workbench";

const PLAN: ArjunaPlan = {
  role: "Software Engineering Intern",
  grounded: true,
  has_resume: true,
  has_job_description: true,
  probes: ["dsa.heaps", "dsa.hash_tables", "dsa.bfs"],
  resume_claims: [{ concept_id: "dsa.bfs", mentions: 2 }],
  job_requirements: [{ concept_id: "dsa.heaps", mentions: 1 }],
  projects: [],
  problems: [
    { id: "p_meeting_rooms_2", title: "Meeting Rooms II", concept_id: "dsa.heaps", difficulty: 2 },
  ],
};

const PROBLEM: ProblemView = {
  id: "p_meeting_rooms_2",
  title: "Meeting Rooms II",
  statement:
    "Given a list of meeting time intervals [start, end] (end is exclusive), return the minimum number of rooms needed so that no two meetings in the same room overlap.",
  difficulty: 2,
  concept_id: "dsa.heaps",
  function: "min_meeting_rooms",
  params: ["intervals"],
  language: "python",
  starter_code:
    '"""Meeting Rooms II"""\n\n\ndef min_meeting_rooms(intervals):\n    # Write your solution here.\n    pass\n',
  examples: [
    {
      label: "example 1",
      input: {
        intervals: [
          [0, 30],
          [5, 10],
          [15, 20],
        ],
      },
      expected: 2,
    },
    {
      label: "example 2",
      input: {
        intervals: [
          [7, 10],
          [2, 4],
        ],
      },
      expected: 1,
    },
  ],
  tests_available: true,
  runnable_languages: ["python", "javascript"],
};

const RUN: AgentRun = {
  id: "r1",
  problem_id: PROBLEM.id,
  status: "failed",
  passed: 5,
  total: 7,
  summary: "Passed 5 of 7 tests.",
  first_failure: "back to back meetings",
  assisted: false,
  at: "2026-10-04T10:00:00Z",
};

/** Mock-data harness for the Arjuna workbench: no voice session, API or sandbox needed. */
export function ArjunaDemo() {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 pb-16 pt-24">
      <h1 className="text-2xl font-semibold">Arjuna workbench (mock)</h1>
      <PlanCard plan={PLAN} />
      <Workbench
        problem={PROBLEM}
        language="python"
        initialCode={PROBLEM.starter_code}
        runs={runs}
        canRun
        onCodeChange={() => {}}
        onLanguageChange={() => {}}
        onRunExamples={async () => ({
          ok: true,
          data: {
            status: "failed",
            passed: 1,
            total: 2,
            summary: "Passed 1 of 2 tests. First failure: example 2 returned a wrong answer.",
            results: [
              {
                label: "example 1",
                passed: true,
                input: {},
                expected: 2,
                actual: null,
                detail: null,
              },
              {
                label: "example 2",
                passed: false,
                input: {},
                expected: 1,
                actual: "2",
                detail: null,
              },
            ],
          },
        })}
      />
      <button
        type="button"
        onClick={() => setRuns((r) => [...r, { ...RUN, id: `r${r.length + 1}` }])}
        className="self-start rounded-xl border border-white/15 px-4 py-2 text-sm"
      >
        Simulate Arjuna running the tests
      </button>
    </main>
  );
}
