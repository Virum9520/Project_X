/**
 * Judging answers in the browser. Deterministic and explainable: an answer is compared with the
 * rubric criteria the question was built from (`cs-core@v1`), and the feedback names exactly
 * which criteria it covered. Answers are data: nothing in them changes how they are judged.
 */

const STOPWORDS = new Set(
  (
    "a an the and or but if then else of to in on at by for with without from into onto over " +
    "under about as is are was were be been being it its this that these those there here their " +
    "them they we you your our i me my he she his her not no nor so than too very can could " +
    "should would will shall may might must do does did done doing have has had having just only " +
    "also both each every either neither any all some such own same other another more most less " +
    "least much many few one two first new use used uses using make makes made like via per etc " +
    "vs versus how why what when where which who whom whose while whereas because since until " +
    "rather instead between within across along upon get gets getting got still even well way"
  ).split(" "),
);

/** Words that describe the learner's behaviour in a criterion, not the content to cover. */
const RUBRIC_VERBS = new Set(
  (
    "explains explain states state describes describe identifies identify gives give names name " +
    "compares compare traces trace recognises recognizes recognise recognize justifies justify " +
    "distinguishes distinguish predicts predict chooses choose shows show tells tell derives " +
    "derive solves solve implements implement computes compute writes write applies apply knows " +
    "know handles handle answers answer adjusts adjust reuses reuse picks pick walks walk " +
    "including include includes example examples given correct correctly words simple concrete " +
    "case cases common commonly typical typically learner candidate"
  ).split(" "),
);

/** Spellings of the same idea, folded into one token before matching. */
const CANONICAL: [RegExp, string][] = [
  [/\bo\s*\(\s*n\s*log\s*n\s*\)|\bn\s*log\s*n\b|\blinearithmic\b/gi, " nlogn "],
  [/\bo\s*\(\s*log\s*n\s*\)|\blogarithmic(?:ally)?\b|\blog\s*n\b|\blog\s*\(\s*n\s*\)/gi, " logn "],
  [/\bo\s*\(\s*1\s*\)|\bconstant[- ]time\b/gi, " o1 "],
  [/\bo\s*\(\s*n\s*(?:\^|\*\*)\s*2\s*\)|\bquadratic\b|\bn\s*squared\b|\bn\^2\b/gi, " n2 "],
  [/\bo\s*\(\s*n\s*\)|\blinear[- ]time\b/gi, " linearn "],
  [/\bo\s*\(\s*2\s*\^\s*n\s*\)|\bexponential\b/gi, " exp2n "],
  [/\blast[- ]in,?\s*first[- ]out\b|\blifo\b/gi, " lifo "],
  [/\bfirst[- ]in,?\s*first[- ]out\b|\bfifo\b/gi, " fifo "],
  [/\bhash\s*(?:map|table)s?\b|\bdictionar(?:y|ies)\b|\bdicts?\b/gi, " hashmap "],
];
const CANONICAL_TOKENS = new Set(CANONICAL.map(([, token]) => token.trim()));

function stem(word: string): string {
  if (word.length > 5 && word.endsWith("ies")) return `${word.slice(0, -3)}y`;
  for (const suffix of ["ing", "ed", "es", "s", "ly"]) {
    if (word.length - suffix.length >= 4 && word.endsWith(suffix))
      return word.slice(0, -suffix.length);
  }
  return word;
}

/** Content tokens of a text, stemmed and de-duplicated. */
export function terms(text: string, { forRubric = false } = {}): string[] {
  let folded = text.toLowerCase();
  for (const [pattern, token] of CANONICAL) folded = folded.replace(pattern, token);
  const out = new Set<string>();
  for (const raw of folded.split(/[^a-z0-9+#]+/)) {
    if (!raw) continue;
    if (CANONICAL_TOKENS.has(raw)) {
      out.add(raw);
      continue;
    }
    if (raw.length < 3 || STOPWORDS.has(raw)) continue;
    if (forRubric && RUBRIC_VERBS.has(raw)) continue;
    out.add(stem(raw));
  }
  return [...out];
}

const sameTerm = (a: string, b: string) =>
  a === b ||
  (Math.min(a.length, b.length) >= 4 &&
    Math.abs(a.length - b.length) <= 3 &&
    (a.startsWith(b) || b.startsWith(a)));

export const wordCount = (text: string) => text.trim().split(/\s+/).filter(Boolean).length;

export interface CriterionResult {
  criterion: string;
  covered: boolean;
  matched: string[];
}

export interface RubricJudgement {
  outcome: "demonstrated" | "partial" | "not_demonstrated";
  covered: CriterionResult[];
  missed: CriterionResult[];
  /** 0..1 share of criteria covered. */
  score: number;
  /** How sure the lexical judge is; short answers are less certain. */
  confidence: number;
}

/** Compare an answer with the rubric criteria a question was built from. */
export function judgeAgainstRubric(answer: string, criteria: string[]): RubricJudgement {
  const said = terms(answer);
  const results: CriterionResult[] = criteria.map((criterion) => {
    const wanted = terms(criterion, { forRubric: true });
    const matched = wanted.filter((w) => said.some((s) => sameTerm(s, w)));
    const needed = wanted.length <= 2 ? 1 : Math.max(2, Math.round(wanted.length * 0.34));
    return { criterion, covered: wanted.length > 0 && matched.length >= needed, matched };
  });
  const covered = results.filter((r) => r.covered);
  const missed = results.filter((r) => !r.covered);
  const score = results.length ? covered.length / results.length : 0;
  const words = wordCount(answer);
  const anyMatch = results.some((r) => r.matched.length > 0);
  let outcome: RubricJudgement["outcome"] = "not_demonstrated";
  if (results.length === 1) {
    if (covered.length === 1) outcome = "demonstrated";
    else if (anyMatch && words >= 12) outcome = "partial";
  } else if (score >= 0.5) outcome = "demonstrated";
  else if (score > 0 || (anyMatch && words >= 20)) outcome = "partial";
  const confidence = Math.min(0.9, 0.62 + Math.min(words, 80) / 400);
  return { outcome, covered, missed, score, confidence };
}

const DISAGREE =
  /\b(no|nope|not|isn'?t|aren'?t|wasn'?t|doesn'?t|don'?t|won'?t|can'?t|cannot|wrong|incorrect|false|untrue|actually|myth|misconception|mistaken|never|disagree|depends)\b/i;
const AGREE_ONLY = /^\s*(yes|yeah|yep|correct|right|true|exactly|agreed|i agree)\b/i;

/**
 * A "classmate says ..." check: the claim is a known misconception, so a good answer disagrees
 * and says why.
 */
export function judgeCorrection(answer: string, misconception: string, criteria: string[]) {
  const disagrees = DISAGREE.test(answer) && !AGREE_ONLY.test(answer);
  const reason = judgeAgainstRubric(answer, [...criteria, misconception]);
  const words = wordCount(answer);
  let outcome: RubricJudgement["outcome"] = "not_demonstrated";
  if (disagrees && words >= 10) outcome = "demonstrated";
  else if (disagrees) outcome = "partial";
  return { outcome, disagrees, confidence: reason.confidence };
}

// ─── STAR stories (Vidura) ──────────────────────────────────────────────────────────────────

const SITUATION =
  /\b(when i|while i|at my|during|last (?:year|summer|semester|spring|fall|winter|month)|in my (?:internship|job|role|class|course|team|project|club|lab|first|second|third|final|last)|internship|semester|hackathon|capstone|(?:our|the|my) team (?:was|had)|i was (?:working|interning|leading|part|on|in|a|the))\b/i;
const TASK =
  /\b(my (?:task|job|goal|role|responsibility)|i (?:needed|had|was asked|was responsible|was supposed|wanted) to|responsible for|the goal was|we needed to|we had to|tasked with|assigned|deadline|requirement)\b/i;
const ACTION =
  /\bi (?:\w+ ){0,2}?(built|wrote|created|designed|implemented|proposed|suggested|organi[sz]ed|scheduled|talked|spoke|met|asked|reached out|decided|led|fixed|debugged|refactored|added|set up|tested|analy[sz]ed|measured|automated|documented|pushed|shipped|presented|explained|listened|split|prioriti[sz]ed|took|started|learned|learnt|changed|reviewed|paired|migrated|rewrote|investigated|traced|profiled|benchmarked|coordinated|delegated|mentored|negotiated|compromised|apologi[sz]ed|owned|volunteered|researched|read|practiced|practised|sketched|drafted|wrote up|followed up|escalated|clarified)\b/gi;
const RESULT =
  /\b(as a result|in the end|eventually|ended up|outcome|result(?:ed|s)?|which (?:meant|led)|so that|reduced|increased|improved|cut|saved|shipped|launched|delivered|finished|completed|passed|won|grew|decreased|faster|fewer|on time|got (?:an?|the)|received|praised|adopted|merged)\b/i;
const REFLECTION =
  /\b(i learned|i learnt|lesson|next time|in hindsight|looking back|i would|i'd (?:do|have|now)|differently|since then|now i|taught me|i realized|i realised)\b/i;
const SPECIFIC =
  /\d|\b(python|java|javascript|typescript|react|node|sql|postgres|aws|docker|kubernetes|api|git|github|jira|figma|excel|flask|django|spring|c\+\+|go|rust|swift|kotlin|linux|redis|kafka|tableau|slack)\b/i;

export type ProbeKey =
  "structure" | "specificity" | "ownership" | "conciseness" | "result" | "reflection";

export interface StarReport {
  situation: boolean;
  task: boolean;
  action: boolean;
  result: boolean;
  reflection: boolean;
  specific: boolean;
  ownership: boolean;
  words: number;
  parts: number;
  outcome: "demonstrated" | "partial" | "not_demonstrated";
  /** The follow-up to ask, for the weakest part of the story. */
  probe: ProbeKey;
  strengths: string[];
}

export function analyseStar(answer: string): StarReport {
  const words = wordCount(answer);
  const situation = SITUATION.test(answer);
  const task = TASK.test(answer);
  const actions = answer.match(ACTION)?.length ?? 0;
  const action = actions > 0;
  const result = RESULT.test(answer);
  const reflection = REFLECTION.test(answer);
  const specific = SPECIFIC.test(answer);
  const iCount = answer.match(/\b(i|my|me)\b/gi)?.length ?? 0;
  const weCount = answer.match(/\b(we|our|us)\b/gi)?.length ?? 0;
  const ownership = iCount >= 2 && iCount >= weCount * 0.5;
  const parts = [situation, task, action, result].filter(Boolean).length;

  let outcome: StarReport["outcome"] = "not_demonstrated";
  if (parts >= 3 && action && words >= 35) outcome = "demonstrated";
  else if (parts >= 2 && words >= 20) outcome = "partial";

  let probe: ProbeKey = "reflection";
  if (!result) probe = "result";
  else if (!action || !ownership) probe = "ownership";
  else if (!situation && !task) probe = "structure";
  else if (!specific) probe = "specificity";
  else if (words > 320) probe = "conciseness";

  const strengths: string[] = [];
  if (situation || task) strengths.push("you set up the situation");
  if (action && ownership) strengths.push("your own actions were clear");
  if (result) strengths.push("you said how it ended");
  if (specific) strengths.push("you gave concrete details");
  if (reflection) strengths.push("you reflected on what you learned");

  return {
    situation,
    task,
    action,
    result,
    reflection,
    specific,
    ownership,
    words,
    parts,
    outcome,
    probe,
    strengths,
  };
}

/** Whether a follow-up answer gives what the probe asked for. */
export function answersProbe(probe: ProbeKey, answer: string): boolean {
  const words = wordCount(answer);
  if (words < 8) return false;
  switch (probe) {
    case "result":
      return RESULT.test(answer) || /\d/.test(answer);
    case "reflection":
      return REFLECTION.test(answer);
    case "ownership":
      return (answer.match(ACTION)?.length ?? 0) > 0;
    case "specificity":
      return SPECIFIC.test(answer);
    case "structure":
      return [SITUATION, TASK, RESULT].filter((r) => r.test(answer)).length >= 2;
    case "conciseness":
      return words <= 60;
  }
}

export function joinList(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** Lower-case the first letter, for quoting a criterion or claim mid-sentence. */
export const lowerFirst = (s: string) => (s ? s.charAt(0).toLowerCase() + s.slice(1) : s);
