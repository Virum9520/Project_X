import type { AgentRun } from "@sg/contracts";

/** Merge newly polled runs into the list: dedupe by id, oldest first. */
export function mergeRuns(
  existing: readonly AgentRun[],
  incoming: readonly AgentRun[],
): AgentRun[] {
  const byId = new Map(existing.map((r) => [r.id, r]));
  for (const run of incoming) byId.set(run.id, run);
  return [...byId.values()].sort((a, b) => a.at.localeCompare(b.at));
}

/** The `after` cursor for the next poll: the newest run seen, or undefined for the first poll. */
export function pollCursor(runs: readonly AgentRun[]): string | undefined {
  return runs.length ? runs[runs.length - 1].at : undefined;
}

export function latestRunFor(runs: readonly AgentRun[], problemId: string): AgentRun | null {
  for (let i = runs.length - 1; i >= 0; i--) if (runs[i].problem_id === problemId) return runs[i];
  return null;
}

const STATUS_LABEL: Record<AgentRun["status"], string> = {
  passed: "All tests passed",
  failed: "Some tests failed",
  error: "The code crashed",
  timeout: "Ran out of time",
};

export function describeRun(run: AgentRun): { headline: string; detail: string; tone: string } {
  const tone =
    run.status === "passed" ? "text-moss" : run.status === "failed" ? "text-ember" : "text-ember";
  const counts = run.total > 0 ? `${run.passed} of ${run.total} passed.` : "";
  const failure = run.first_failure ? `First failure: ${run.first_failure}.` : "";
  return {
    headline: STATUS_LABEL[run.status],
    detail: [counts, failure, run.assisted ? "After a hint." : ""].filter(Boolean).join(" "),
    tone,
  };
}
