/**
 * Turning rubric criteria ("Explains why the input must be sorted") into what a coach says:
 * "you explained why the input must be sorted", "explain why the input must be sorted".
 */

const VERBS = new Set(
  (
    "explains states describes identifies gives names compares traces recognises recognizes " +
    "justifies distinguishes predicts chooses shows tells derives solves implements computes " +
    "writes applies uses knows handles answers adjusts reuses picks walks orders sketches " +
    "designs estimates defines lists reasons argues analyzes analyses evaluates proposes builds " +
    "discusses maps converts calculates detects avoids prevents relates connects contrasts " +
    "outlines selects plans prioritizes communicates reflects separates measures checks keeps " +
    "makes finds takes leads spends draws gets runs adapts adds counts covers debugs decides " +
    "determines diagnoses evolves extends follows generates locates mentions merges models " +
    "normalizes owns places produces reads redesigns reduces reverses routes splits spots " +
    "tailors turns validates weighs wraps binary-searches"
  ).split(" "),
);

/** After "and"/"or" these are usually nouns ("reads and writes", "metrics and traces"). */
const NOT_SECOND_VERBS = new Set(["writes", "traces", "reads"]);

const IRREGULAR_PAST: Record<string, string> = {
  gives: "gave",
  chooses: "chose",
  tells: "told",
  writes: "wrote",
  knows: "knew",
  makes: "made",
  builds: "built",
  finds: "found",
  takes: "took",
  leads: "led",
  keeps: "kept",
  spends: "spent",
  draws: "drew",
  gets: "got",
  runs: "ran",
  reads: "read",
  splits: "split",
  sets: "set",
  puts: "put",
  debugs: "debugged",
  spots: "spotted",
  wraps: "wrapped",
  maps: "mapped",
  plans: "planned",
};

function baseForm(verb: string): string {
  if (verb.endsWith("ies")) return `${verb.slice(0, -3)}y`;
  if (/(ss|sh|ch|x|zz)es$/.test(verb)) return verb.slice(0, -2);
  return verb.endsWith("s") ? verb.slice(0, -1) : verb;
}

function pastForm(verb: string): string {
  if (IRREGULAR_PAST[verb]) return IRREGULAR_PAST[verb];
  if (verb.endsWith("ies")) return `${verb.slice(0, -3)}ied`;
  const base = baseForm(verb);
  return base.endsWith("e") ? `${base}d` : `${base}ed`;
}

const trimEnd = (s: string) => s.trim().replace(/[.;:]+$/, "");
export const lowerFirst = (s: string) => (s ? s.charAt(0).toLowerCase() + s.slice(1) : s);

function split(criterion: string): { verb: string | null; rest: string } {
  const text = trimEnd(criterion);
  const [first = "", ...rest] = text.split(/\s+/);
  const verb = first.toLowerCase();
  return VERBS.has(verb) && rest.length
    ? { verb, rest: rest.join(" ") }
    : { verb: null, rest: lowerFirst(text) };
}

/** A second verb joined by "and"/"or" takes the same form: "states X and chooses Y". */
const conjugateRest = (rest: string, form: (verb: string) => string) =>
  rest.replace(/\b(and|or|then) ([a-z]+)\b/g, (match, conj: string, word: string) =>
    VERBS.has(word) && !NOT_SECOND_VERBS.has(word) ? `${conj} ${form(word)}` : match,
  );

/** "you explained why …" (or "you covered that …" when the criterion is a statement). */
export function coveredLine(criterion: string): string {
  const { verb, rest } = split(criterion);
  return verb
    ? `you ${pastForm(verb)} ${conjugateRest(rest, pastForm)}`
    : `you covered that ${rest}`;
}

/** "explain why …" for a nudge (or "mention that …"). */
export function todoLine(criterion: string): string {
  const { verb, rest } = split(criterion);
  return verb ? `${baseForm(verb)} ${conjugateRest(rest, baseForm)}` : `mention that ${rest}`;
}

/** A spoken question for a criterion: "How would you implement …? Walk me through it." */
export function questionFor(criterion: string): string | null {
  const { verb, rest } = split(criterion);
  return verb
    ? `How would you ${baseForm(verb)} ${conjugateRest(rest, baseForm)}? Walk me through it.`
    : null;
}

export const pick = <T>(items: readonly T[]): T => items[Math.floor(Math.random() * items.length)]!;

export const sentence = (s: string) => {
  const t = s.trim();
  return t ? `${t.charAt(0).toUpperCase()}${t.slice(1)}${/[.!?]$/.test(t) ? "" : "."}` : t;
};
