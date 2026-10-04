"use client";

import type { RunnableLanguage } from "@sg/contracts";
import { loader } from "@monaco-editor/react";

import { asset, type ProblemCase } from "./bank";

/**
 * Runs a solution against test cases in this browser: JavaScript directly, TypeScript after
 * Monaco's own compiler strips the types, and Python on Pyodide (loaded the first time Python
 * runs). Each case runs in a worker under a time limit, like the sandbox harness: a case that
 * runs too long is stopped and reported as a timeout.
 */

loader.config({ paths: { vs: asset("/monaco/vs") } });

export type CaseStatus = "pass" | "fail" | "error" | "timeout" | "skipped";

export interface CaseOutcome {
  index: number;
  label: string;
  status: CaseStatus;
  /** JSON of what the code returned, for failed public examples. */
  actual: string | null;
  detail: string | null;
}

interface WorkerResult {
  status: "ok" | "error";
  value?: unknown;
  undef?: boolean;
  detail?: string;
}

type Reply = { id: number; ready?: boolean; result?: WorkerResult };

const PYODIDE_BASE = () => `${window.location.origin}${asset("/pyodide/")}`;
const MAX_DETAIL = 240;

// Browsers run slower than the sandbox; give each case some headroom on top of its limit.
const SLOWDOWN: Record<RunnableLanguage, number> = { python: 3, javascript: 2, typescript: 2 };

let worker: Worker | null = null;
let pythonReady = false;
let nextId = 1;

function getWorker(): Worker {
  worker ??= new Worker(asset("/runner/worker.mjs"), { type: "module" });
  return worker;
}

function resetWorker() {
  worker?.terminate();
  worker = null;
  pythonReady = false;
}

function ask(message: Record<string, unknown>, timeoutMs: number): Promise<Reply | "timeout"> {
  const w = getWorker();
  const id = nextId++;
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      w.removeEventListener("message", onMessage);
      resolve("timeout");
    }, timeoutMs);
    const onMessage = (event: MessageEvent<Reply>) => {
      if (event.data.id !== id) return;
      window.clearTimeout(timer);
      w.removeEventListener("message", onMessage);
      resolve(event.data);
    };
    w.addEventListener("message", onMessage);
    w.postMessage({ ...message, id });
  });
}

/** Load Python ahead of time (a few seconds, once per page). */
export async function warmPython(): Promise<void> {
  if (pythonReady) return;
  const reply = await ask(
    { kind: "warm", language: "python", pyodideBase: PYODIDE_BASE() },
    90_000,
  );
  if (reply === "timeout" || !reply.ready) {
    resetWorker();
    throw new Error("Python could not load in this browser. Try JavaScript, or reload the page.");
  }
  pythonReady = true;
}

// ── TypeScript via Monaco's TypeScript worker ──────────────────────────────────────────────

interface TsWorker {
  getEmitOutput(fileName: string): Promise<{ outputFiles: { name: string; text: string }[] }>;
}
interface TsApi {
  getTypeScriptWorker(): Promise<(...uris: unknown[]) => Promise<TsWorker>>;
}
interface MonacoForTs {
  Uri: { parse(value: string): { toString(): string } };
  editor: { createModel(value: string, language: string, uri: unknown): { dispose(): void } };
  typescript?: TsApi;
  languages: { typescript?: TsApi };
}

let tsFile = 0;

export async function compileTypeScript(code: string): Promise<string> {
  const monaco = (await loader.init()) as unknown as MonacoForTs;
  const api = monaco.typescript ?? monaco.languages.typescript;
  if (!api) throw new Error("The TypeScript compiler is not available.");
  const uri = monaco.Uri.parse(`file:///solution-${++tsFile}.ts`);
  const model = monaco.editor.createModel(code, "typescript", uri);
  try {
    const worker = await (await api.getTypeScriptWorker())(uri);
    const output = await worker.getEmitOutput(uri.toString());
    const js = output.outputFiles.find((f) => f.name.endsWith(".js"))?.text;
    if (js === undefined) throw new Error("The TypeScript could not be compiled.");
    return js;
  } finally {
    model.dispose();
  }
}

// ── Running cases ──────────────────────────────────────────────────────────────────────────

/** Strict JSON equality, as the harness compares results. */
export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null) return false;
  if (Array.isArray(a))
    return Array.isArray(b) && a.length === b.length && a.every((x, i) => deepEqual(x, b[i]));
  if (typeof a === "object") {
    const ka = Object.keys(a as object);
    const kb = Object.keys(b as object);
    return (
      ka.length === kb.length &&
      ka.every((k) =>
        deepEqual((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]),
      )
    );
  }
  return false;
}

export interface RunRequest {
  language: RunnableLanguage;
  code: string;
  /** Function name in this language (snake_case for Python, camelCase otherwise). */
  fn: string;
  cases: ProblemCase[];
  timeLimitS: number;
  onStatus?: (message: string) => void;
}

export async function runCases(req: RunRequest): Promise<CaseOutcome[]> {
  let code = req.code;
  const language = req.language;
  const failAll = (detail: string): CaseOutcome[] =>
    req.cases.map((c, index) => ({
      index,
      label: c.label,
      status: "error",
      actual: null,
      detail: detail.slice(0, MAX_DETAIL),
    }));

  if (language === "typescript") {
    try {
      code = await compileTypeScript(code);
    } catch (e) {
      return failAll(e instanceof Error ? e.message : "The TypeScript could not be compiled.");
    }
  }
  if (language === "python" && !pythonReady) {
    req.onStatus?.("Loading Python in your browser (first run only)…");
    try {
      await warmPython();
    } catch (e) {
      return failAll(e instanceof Error ? e.message : "Python could not load.");
    }
  }

  const engine = language === "python" ? "python" : "javascript";
  const limitMs = req.timeLimitS * 1000 * SLOWDOWN[language] + 250;
  const outcomes: CaseOutcome[] = [];
  let stopped = false;
  for (const [index, c] of req.cases.entries()) {
    if (stopped) {
      outcomes.push({ index, label: c.label, status: "skipped", actual: null, detail: null });
      continue;
    }
    req.onStatus?.(`Running ${index + 1} of ${req.cases.length}…`);
    const reply = await ask(
      {
        kind: "case",
        language: engine,
        code,
        fn: req.fn,
        args: c.args,
        pyodideBase: PYODIDE_BASE(),
      },
      limitMs,
    );
    if (reply === "timeout") {
      // The worker may be stuck in a loop: replace it, and stop here like a crashed harness.
      resetWorker();
      outcomes.push({ index, label: c.label, status: "timeout", actual: null, detail: null });
      stopped = true;
      continue;
    }
    const result = reply.result ?? { status: "error", detail: "no result" };
    if (result.status === "error") {
      outcomes.push({
        index,
        label: c.label,
        status: "error",
        actual: null,
        detail: (result.detail ?? "error").slice(0, MAX_DETAIL),
      });
      continue;
    }
    const passed = !result.undef && deepEqual(result.value, c.expected);
    outcomes.push({
      index,
      label: c.label,
      status: passed ? "pass" : "fail",
      actual: passed
        ? null
        : (result.undef ? "undefined" : JSON.stringify(result.value)).slice(0, MAX_DETAIL),
      detail: null,
    });
  }
  return outcomes;
}
