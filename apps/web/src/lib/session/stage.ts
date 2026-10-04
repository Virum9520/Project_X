/**
 * Voice-stage state and the client tools Drona calls in the browser.
 *
 * Arguments come from an LLM, so every tool validates them and answers with a plain sentence the
 * agent can speak (success or a correctable error). Handlers never throw. The stage state is a
 * pure reducer so it can be tested without React or a conversation.
 */
import type {
  FocusPlantArgs,
  LiveGrowthEvent,
  HighlightPlantArgs,
  OpenEditorArgs,
  QuestionKind,
  ShowDiagramArgs,
  ShowQuestionCardArgs,
} from "@sg/contracts";

import { parseQuestionId } from "./question-id";

export const MAX_TICKER = 12;
/** How long a plant keeps glowing after a growth event or a highlight. */
export const PULSE_MS = 9000;

export interface QuestionCard {
  questionId: string;
  title: string;
  body: string;
  kind: QuestionKind | null;
  conceptId: string | null;
}

export interface TickerEntry {
  id: string;
  kind: LiveGrowthEvent["kind"];
  conceptId: string;
  part: LiveGrowthEvent["part"];
  assisted: boolean;
  quote: string;
  reason: string;
  at: string;
}

export interface Highlight {
  conceptId: string;
  part: NonNullable<HighlightPlantArgs["part"]>;
  until: number;
}

export interface StageState {
  card: QuestionCard | null;
  /** True once a Teach-back question was shown: the learner is now the teacher. */
  teachBack: boolean;
  teachBackStartedAt: number | null;
  editor: OpenEditorArgs | null;
  diagram: { id: string; caption: string } | null;
  highlight: Highlight | null;
  focus: FocusPlantArgs | null;
  ticker: TickerEntry[];
}

export const INITIAL_STAGE: StageState = {
  card: null,
  teachBack: false,
  teachBackStartedAt: null,
  editor: null,
  diagram: null,
  highlight: null,
  focus: null,
  ticker: [],
};

export type StageAction =
  | { type: "card"; card: QuestionCard; now: number }
  | { type: "editor"; editor: OpenEditorArgs }
  | { type: "diagram"; id: string; caption: string }
  | { type: "highlight"; highlight: Highlight }
  | { type: "focus"; focus: FocusPlantArgs }
  | { type: "growth"; event: LiveGrowthEvent }
  | { type: "dismiss"; what: "card" | "editor" | "diagram" | "focus" }
  | { type: "endTeachBack" }
  | { type: "reset" };

export function stageReducer(state: StageState, action: StageAction): StageState {
  switch (action.type) {
    case "card": {
      // A Teach-back card flips the learner into the teacher role; any other known question
      // kind ends it. A card whose ID we cannot parse leaves the role alone.
      const teachBack =
        action.card.kind === "teach_back" || (state.teachBack && action.card.kind === null);
      return {
        ...state,
        card: action.card,
        teachBack,
        teachBackStartedAt: teachBack ? (state.teachBackStartedAt ?? action.now) : null,
      };
    }
    case "editor":
      return { ...state, editor: action.editor };
    case "diagram":
      return { ...state, diagram: { id: action.id, caption: action.caption } };
    case "highlight":
      return { ...state, highlight: action.highlight };
    case "focus":
      return { ...state, focus: action.focus };
    case "growth": {
      const e = action.event;
      const entry: TickerEntry = {
        id: e.id,
        kind: e.kind,
        conceptId: e.conceptId,
        part: e.part,
        assisted: e.assisted,
        quote: e.quote,
        reason: e.reason,
        at: e.occurredAt,
      };
      // A confirmation or retraction replaces the provisional entry it settles.
      const rest = state.ticker.filter(
        (t) =>
          !(
            (e.kind === "confirmed" || e.kind === "retracted") &&
            t.kind === "provisional" &&
            t.conceptId === e.conceptId &&
            t.part === e.part
          ) && t.id !== e.id,
      );
      return { ...state, ticker: [entry, ...rest].slice(0, MAX_TICKER) };
    }
    case "dismiss":
      return { ...state, [action.what]: null };
    case "endTeachBack":
      return { ...state, teachBack: false, teachBackStartedAt: null };
    case "reset":
      return INITIAL_STAGE;
  }
}

/** Concept ids that should glow at `now`: live growth, plus a highlight Drona asked for. */
export function pulseConceptIds(state: StageState, live: ReadonlySet<string>, now: number) {
  const ids = new Set(live);
  if (state.highlight && state.highlight.until > now) ids.add(state.highlight.conceptId);
  return ids;
}

// ─── Client tools ──────────────────────────────────────────────────────────────────────────

const CONCEPT_KEY = /^[a-z0-9_]+(\.[a-z0-9_]+)+$/;
const PARTS = ["whole", "roots", "stem", "branches", "blossoms"] as const;
const LANGUAGES = ["python", "javascript", "typescript", "java", "cpp", "go"] as const;
const DIAGRAM_ID = /^[A-Za-z0-9_.:-]{1,80}$/;

export interface StageToolDeps {
  dispatch: (action: StageAction) => void;
  now: () => number;
  /** Concept keys that exist in the learner's garden. */
  hasConcept: (key: string) => boolean;
  /** The focus_plant handler bound to the garden state (resolves and applies the camera move). */
  focusPlant: (args: FocusPlantArgs) => string;
}

const text = (v: unknown, max: number) =>
  typeof v === "string" ? v.replace(/\s+/g, " ").trim().slice(0, max) : "";

/**
 * Handlers shaped for ElevenLabs' `clientTools`. Tools Drona can call during a session:
 * `show_question_card`, `highlight_plant`, `open_editor`, `show_diagram`, `focus_plant`.
 */
export function createStageTools(deps: StageToolDeps) {
  const { dispatch, now, hasConcept } = deps;
  return {
    show_question_card: (args: Partial<ShowQuestionCardArgs>) => {
      const questionId = text(args.question_id, 200);
      const title = text(args.title, 80);
      const body = text(args.body, 600);
      if (!questionId || !body) return "question_id and body are required.";
      const parsed = parseQuestionId(questionId);
      dispatch({
        type: "card",
        now: now(),
        card: {
          questionId,
          title: title || "Question",
          body,
          kind: parsed?.kind ?? null,
          conceptId: parsed?.conceptKey ?? null,
        },
      });
      return parsed?.kind === "teach_back"
        ? "Teach-back card is on screen. The learner is now the teacher."
        : "Question card is on screen.";
    },

    highlight_plant: (args: Partial<HighlightPlantArgs>) => {
      const id = text(args.concept_id, 128);
      if (!CONCEPT_KEY.test(id)) return 'concept_id must look like "dsa.binary_search".';
      if (!hasConcept(id)) return `Unknown concept "${id}". Use a curriculum concept ID.`;
      const part = args.part ?? "whole";
      if (!(PARTS as readonly string[]).includes(part))
        return `part must be one of ${PARTS.join(", ")}.`;
      dispatch({
        type: "highlight",
        highlight: { conceptId: id, part, until: now() + PULSE_MS },
      });
      return `Highlighted ${id}.`;
    },

    open_editor: (args: Partial<OpenEditorArgs>) => {
      const problemId = text(args.problem_id, 200);
      const language = args.language;
      if (!problemId) return "problem_id is required.";
      if (!language || !(LANGUAGES as readonly string[]).includes(language))
        return `language must be one of ${LANGUAGES.join(", ")}.`;
      dispatch({ type: "editor", editor: { problem_id: problemId, language } });
      return "Editor opened.";
    },

    show_diagram: (args: Partial<ShowDiagramArgs>) => {
      const id = text(args.diagram_id, 80);
      if (!DIAGRAM_ID.test(id)) return "diagram_id is missing or malformed.";
      dispatch({ type: "diagram", id, caption: text(args.caption, 120) });
      return "Diagram is on screen.";
    },

    focus_plant: (args: Partial<FocusPlantArgs>) => {
      const message = deps.focusPlant(args as FocusPlantArgs);
      dispatch({ type: "dismiss", what: "focus" });
      return message;
    },
  };
}

export type StageTools = ReturnType<typeof createStageTools>;
