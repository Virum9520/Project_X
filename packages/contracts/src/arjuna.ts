/**
 * Arjuna technical interview (C16): wire types for `/v1/arjuna/*` (snake_case, mirroring the
 * Pydantic models in `services/api/src/sg_api/arjuna/router.py`) and the shapes the editor uses.
 *
 * Hidden tests never appear here: the browser only ever sees public examples and, for runs the
 * agent made, a summary and the label of the first failing case.
 */
import type { SessionStartResponse } from "./session";

/** Languages tests run for; the editor also allows the others without test runs. */
export const RUNNABLE_LANGUAGES = ["python", "javascript"] as const;
export type RunnableLanguage = (typeof RUNNABLE_LANGUAGES)[number];
export type EditorLanguage = "python" | "javascript" | "typescript" | "java" | "cpp" | "go";

export interface ConceptMention {
  concept_id: string;
  mentions: number;
}

export interface PlanProblem {
  id: string;
  title: string;
  concept_id: string;
  difficulty: number;
}

/** What Arjuna will cover, from the learner's uploaded résumé and job description. */
export interface ArjunaPlan {
  role: string;
  /** False when no document produced a match and the plan is the default fundamentals. */
  grounded: boolean;
  has_resume: boolean;
  has_job_description: boolean;
  probes: string[];
  /** Self-reported on the résumé: used to choose questions, never as evidence. */
  resume_claims: ConceptMention[];
  job_requirements: ConceptMention[];
  projects: string[];
  problems: PlanProblem[];
}

export interface ArjunaSessionStart extends SessionStartResponse {
  plan: ArjunaPlan;
  language: RunnableLanguage;
}

export interface ProblemExample {
  label: string;
  input: Record<string, unknown>;
  expected: unknown;
}

export interface ProblemView {
  id: string;
  title: string;
  statement: string;
  difficulty: number;
  concept_id: string;
  function: string;
  params: string[];
  language: EditorLanguage;
  starter_code: string;
  examples: ProblemExample[];
  /** False for languages the sandbox has no harness for. */
  tests_available: boolean;
  runnable_languages: string[];
}

export interface ExampleResult {
  label: string;
  passed: boolean;
  input: Record<string, unknown>;
  expected: unknown;
  actual: string | null;
  detail: string | null;
}

export interface RunExamplesResult {
  status: string;
  passed: number;
  total: number;
  summary: string;
  results: ExampleResult[];
}

/** One test run made by Arjuna's `run_tests` tool. */
export interface AgentRun {
  id: string;
  problem_id: string;
  status: "passed" | "failed" | "error" | "timeout";
  passed: number;
  total: number;
  summary: string;
  /** Label of the first failing case ("empty input"), never its contents. */
  first_failure: string | null;
  /** True when Arjuna had given a hint on this problem: the evidence is assisted. */
  assisted: boolean;
  at: string;
}

export interface SnapshotAck {
  snapshot_id: string;
  duplicate: boolean;
}
