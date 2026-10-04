import type { ArjunaPlan, ProblemView, RunnableLanguage } from "@sg/contracts";

import type { Bank, BankProblem } from "./bank";

/** Problem choice and the interview plan, ported from `sg_api.arjuna.problems` and `.plan`. */

export function problemsForConcept(bank: Bank, conceptKey: string): BankProblem[] {
  const byDifficulty = (a: BankProblem, b: BankProblem) => a.difficulty - b.difficulty;
  const own = bank.problems.filter((p) => p.concept_id === conceptKey).sort(byDifficulty);
  const related = bank.problems
    .filter((p) => p.secondary_concepts.includes(conceptKey))
    .sort(byDifficulty);
  return [...own, ...related];
}

/**
 * The next problem: unused ones first, then a family not yet seen (so a second problem is a real
 * transfer test). Returns whether it matched the concept.
 */
export function selectProblem(
  bank: Bank,
  conceptKey: string | null,
  options: { exclude?: Set<string>; excludeFamilies?: Set<string>; harder?: boolean } = {},
): { problem: BankProblem; matched: boolean } {
  let candidates = conceptKey ? problemsForConcept(bank, conceptKey) : [];
  const matched = candidates.length > 0;
  if (!matched)
    candidates = [...bank.problems].sort(
      (a, b) => a.difficulty - b.difficulty || a.id.localeCompare(b.id),
    );
  const fresh = candidates.filter((p) => !options.exclude?.has(p.id));
  const pool = fresh.length ? fresh : candidates;
  const newFamily = pool.filter((p) => !options.excludeFamilies?.has(p.family));
  let ordered = newFamily.length ? newFamily : pool;
  if (options.harder) ordered = [...ordered].sort((a, b) => b.difficulty - a.difficulty);
  return { problem: ordered[0]!, matched };
}

export function toProblemView(problem: BankProblem, language: RunnableLanguage): ProblemView {
  return {
    id: problem.id,
    title: problem.title,
    statement: problem.statement,
    difficulty: problem.difficulty,
    concept_id: problem.concept_id,
    function: language === "python" ? problem.function : problem.js_function,
    params: problem.params,
    language,
    starter_code: problem.starter[language],
    examples: problem.examples,
    tests_available: true,
    runnable_languages: ["python", "javascript", "typescript"],
  };
}

// ── Interview plan from a résumé and job description ───────────────────────────────────────

const MAX_TEXT_CHARS = 60_000;
const ACTION_LINE =
  /\b(built|developed|implemented|designed|created|led|architected|shipped|optimi[sz]ed|reduced|improved|wrote|launched)\b/i;
const INSTRUCTION_LIKE =
  /ignore (?:all |any )?(?:the )?(?:previous|prior|above)|disregard|you are now|new instructions|system prompt|as an ai|<\s*\/?\s*(?:system|assistant|tool)\b|\bassistant\s*:|\bsystem\s*:|reveal|jailbreak|pretend/i;
const MARKUP = /[<>{}`[\]\\|]/g;
// Control characters are stripped; tab and newline are kept.
const CONTROL = /[\x00-\x08\x0b-\x1f\x7f]/g;
const BULLETS = /^[\s\-*•·▪●◦>\d.)]+/;

const clean = (text: string) => text.replace(CONTROL, " ").slice(0, MAX_TEXT_CHARS);
const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");

function phrasePattern(phrases: string[]): RegExp {
  const sorted = [...phrases].sort((a, b) => b.length - a.length).map(escape);
  return new RegExp(`(?<![\\w-])(?:${sorted.join("|")})(?![\\w-])`, "gi");
}

export interface Mention {
  concept_id: string;
  mentions: number;
}

/** Concepts mentioned in `text`, most mentioned first (ties by concept key). */
export function countMentions(bank: Bank, text: string, known: Set<string>): Mention[] {
  const body = clean(text);
  const out: Mention[] = [];
  for (const [key, phrases] of Object.entries(bank.plan.lexicon)) {
    if (!known.has(key)) continue;
    const hits = body.match(phrasePattern(phrases))?.length ?? 0;
    if (hits) out.push({ concept_id: key, mentions: hits });
  }
  return out.sort((a, b) => b.mentions - a.mentions || a.concept_id.localeCompare(b.concept_id));
}

/** Up to a few short résumé lines about things the learner says they built. */
export function projectLines(bank: Bank, resume: string): string[] {
  const out: string[] = [];
  for (const raw of clean(resume).split(/\r?\n/)) {
    const line = raw.replace(BULLETS, "").trim();
    if (line.length < 25 || line.length > 220 || !ACTION_LINE.test(line)) continue;
    if (INSTRUCTION_LIKE.test(line)) continue;
    const tidy = line.replace(MARKUP, " ").split(/\s+/).join(" ");
    if (tidy && !out.includes(tidy)) out.push(tidy);
    if (out.length >= bank.plan.max_projects) break;
  }
  return out;
}

/**
 * Plan an interview. Deterministic: a lexicon of terms counted in the text, so nothing written
 * in a document can steer the interview. Résumé items are claims; only answers earn growth.
 */
export function buildPlan(
  bank: Bank,
  input: { role: string; resume: string; jobDescription: string },
): ArjunaPlan {
  const known = new Set(bank.concepts.map((c) => c.key));
  const claims = input.resume.trim() ? countMentions(bank, input.resume, known) : [];
  const requirements = input.jobDescription.trim()
    ? countMentions(bank, input.jobDescription, known)
    : [];
  const probes: string[] = [];
  const add = (key: string) => {
    if (known.has(key) && !probes.includes(key) && probes.length < bank.plan.max_probes)
      probes.push(key);
  };
  const ordered = [...requirements, ...claims].map((m) => m.concept_id);
  for (const key of ordered) if (problemsForConcept(bank, key).length) add(key);
  for (const key of ordered) add(key);
  for (const key of bank.plan.fallback_probes) add(key);

  const problems: ArjunaPlan["problems"] = [];
  for (const key of probes) {
    const first = problemsForConcept(bank, key)[0];
    if (
      first &&
      !problems.some((p) => p.id === first.id) &&
      problems.length < bank.plan.max_problems
    )
      problems.push({
        id: first.id,
        title: first.title,
        concept_id: first.concept_id,
        difficulty: first.difficulty,
      });
  }
  return {
    role: input.role.trim() || "Software Engineering Intern",
    grounded: claims.length > 0 || requirements.length > 0,
    has_resume: Boolean(input.resume.trim()),
    has_job_description: Boolean(input.jobDescription.trim()),
    probes,
    resume_claims: claims.slice(0, bank.plan.max_probes),
    job_requirements: requirements.slice(0, bank.plan.max_probes),
    projects: input.resume.trim() ? projectLines(bank, input.resume) : [],
    problems,
  };
}
