"use client";

import type { Dimension, ProblemExample, RunnableLanguage } from "@sg/contracts";
import { useEffect, useState } from "react";

/**
 * The practice content the browser runs on: Drona's rubric questions, Vidura's STAR bank,
 * Arjuna's problem bank and the résumé lexicon. `scripts/export-practice-data.py` writes it from
 * the API's own modules at build time, so it matches what the full app asks.
 */

/** GitHub Pages serves the site from a sub-path; static files need it, Next links do not. */
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
export const asset = (path: string) => `${BASE_PATH}${path}`;

export type QuestionKindKey = "concept_check" | "cross_question" | "teach_back" | "behavioral";

export interface BankQuestion {
  id: string;
  prompt: string;
  /** What a good answer covers (rubric criteria), or follow-up probes for behavioural prompts. */
  hints: string[];
}

export interface BankConcept {
  key: string;
  title: string;
  grove: string;
  summary: string;
  difficulty: number;
  rubric: Partial<Record<Dimension | "misconceptions", string[]>>;
  questions: Partial<Record<QuestionKindKey, BankQuestion[]>>;
}

export interface BankProblem {
  id: string;
  family: string;
  concept_id: string;
  secondary_concepts: string[];
  title: string;
  difficulty: number;
  statement: string;
  function: string;
  js_function: string;
  params: string[];
  examples: ProblemExample[];
  hidden_count: number;
  hints: string[];
  time_limit_s: number;
  starter: Record<RunnableLanguage, string>;
}

export interface Bank {
  curriculum: string;
  concepts: BankConcept[];
  behavioral: {
    rotation: string[];
    probes: Record<string, string>;
    bank: Record<string, string[]>;
  };
  problems: BankProblem[];
  plan: {
    lexicon: Record<string, string[]>;
    fallback_probes: string[];
    max_probes: number;
    max_projects: number;
    max_problems: number;
  };
}

/** One test case with its expected value (public examples and hidden cases). */
export interface ProblemCase {
  label: string;
  args: unknown[];
  expected: unknown;
  public: boolean;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(asset(path));
  if (!response.ok) throw new Error(`Could not load ${path} (${response.status}).`);
  return (await response.json()) as T;
}

let bankPromise: Promise<Bank> | null = null;

export function loadBank(): Promise<Bank> {
  bankPromise ??= getJson<Bank>("/practice/bank.json").catch((error: unknown) => {
    bankPromise = null;
    throw error;
  });
  return bankPromise;
}

const casesCache = new Map<string, Promise<ProblemCase[]>>();

/** Every case of a problem. Fetched on demand: hidden cases include large inputs. */
export function loadCases(problemId: string): Promise<ProblemCase[]> {
  let cases = casesCache.get(problemId);
  if (!cases) {
    cases = getJson<ProblemCase[]>(`/practice/problems/${problemId}.json`).catch(
      (error: unknown) => {
        casesCache.delete(problemId);
        throw error;
      },
    );
    casesCache.set(problemId, cases);
  }
  return cases;
}

export function useBank(): { bank: Bank | null; error: string | null } {
  const [state, setState] = useState<{ bank: Bank | null; error: string | null }>({
    bank: null,
    error: null,
  });
  useEffect(() => {
    let live = true;
    loadBank().then(
      (bank) => live && setState({ bank, error: null }),
      () =>
        live &&
        setState({ bank: null, error: "Practice content could not load. Reload to try again." }),
    );
    return () => {
      live = false;
    };
  }, []);
  return state;
}

export const conceptByKey = (bank: Bank, key: string) => bank.concepts.find((c) => c.key === key);
