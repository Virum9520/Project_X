/**
 * Voice sessions (C12): `POST /v1/sessions`, the live growth stream, and the client tools Drona
 * calls in the browser (`agents/tools/{show_question_card,highlight_plant,open_editor,show_diagram}.yaml`).
 * Wire format of the API is snake_case for sessions and camelCase for growth events.
 */

export type SessionCharacter =
  "drona" | "arjuna" | "vidura" | "panel" | "bhima" | "krishna" | "sanjaya";

export interface SessionStartRequest {
  character: SessionCharacter;
  focus_concept_id?: string;
  persona_tone?: "energetic" | "calm";
  /** Drona only. */
  mode?: "concept_exam" | "teach_back";
}

export interface SessionStartResponse {
  session_id: string;
  character: SessionCharacter;
  agent_id: string;
  conversation_id: string | null;
  conversation_token: string;
  /** Includes the server-tool token. Keep in memory only; never log or persist. */
  dynamic_variables: Record<string, string>;
  tool_token_expires_at: string;
  /** False when the learner has no `users` row yet: the call works but leaves no records. */
  persisted: boolean;
}

/** One event on `GET /v1/live/growth` (SSE event name `growth`). */
export type LiveGrowthKind = "provisional" | "confirmed" | "retracted" | "noted";
export type LiveGrowthOutcome = "demonstrated" | "partial" | "not_demonstrated" | "unassessable";

export interface LiveGrowthEvent {
  id: string;
  kind: LiveGrowthKind;
  sessionId: string;
  /** Concept key, e.g. `dsa.binary_search`; the same string as the scene's concept id. */
  conceptId: string;
  questionId: string | null;
  dimension: string;
  /** Plant part that glows or grows; null when nothing grows. */
  part: "roots" | "stem" | "branches" | "blossoms" | null;
  outcome: LiveGrowthOutcome;
  /** Assisted evidence renders as a ghost part, never as independent growth. */
  assisted: boolean;
  quote: string;
  note: string;
  judge: string;
  /** Why growth was retracted (kind `retracted`). */
  reason: string;
  occurredAt: string;
}

/** Question IDs are `kind:concept_key:variant` (see `sg_api.drona.questions`). */
export const QUESTION_KINDS = [
  "concept_check",
  "cross_question",
  "teach_back",
  "coding_problem",
  "behavioral",
] as const;
export type QuestionKind = (typeof QUESTION_KINDS)[number];

export interface ShowQuestionCardArgs {
  question_id: string;
  title: string;
  body: string;
}
export interface HighlightPlantArgs {
  concept_id: string;
  part?: "whole" | "roots" | "stem" | "branches" | "blossoms";
}
export interface OpenEditorArgs {
  problem_id: string;
  language: "python" | "javascript" | "typescript" | "java" | "cpp" | "go";
}
export interface ShowDiagramArgs {
  diagram_id: string;
  caption?: string;
}
