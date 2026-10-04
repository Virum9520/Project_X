import { QUESTION_KINDS, type QuestionKind } from "@sg/contracts";

export interface ParsedQuestionId {
  kind: QuestionKind;
  conceptKey: string;
  variant: number;
}

/** `kind:concept_key:variant`, as built by `sg_api.drona.questions.question_id`. */
export function parseQuestionId(id: string): ParsedQuestionId | null {
  const parts = id.split(":");
  if (parts.length !== 3) return null;
  const [kind, conceptKey, variant] = parts;
  if (!(QUESTION_KINDS as readonly string[]).includes(kind) || !/^\d+$/.test(variant)) return null;
  return { kind: kind as QuestionKind, conceptKey, variant: Number(variant) };
}
