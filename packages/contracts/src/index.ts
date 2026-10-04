/**
 * Shared API contracts. Generated types from the FastAPI OpenAPI schema land in
 * `./generated.ts` (Phase 1); hand-written domain enums live here.
 */

/** Characters that run sessions with the learner. */
export const CHARACTERS = ["drona", "arjuna", "vidura", "bhima", "krishna", "sanjaya"] as const;
export type Character = (typeof CHARACTERS)[number];

/** Evidence dimensions and the plant part each one grows. */
export const DIMENSION_TO_PART = {
  explanation: "roots",
  application: "stem",
  transfer: "branches",
  retention: "blossoms",
} as const;
export type Dimension = keyof typeof DIMENSION_TO_PART;
export type PlantPart = (typeof DIMENSION_TO_PART)[Dimension];

/** Lifecycle stage of a concept plant in the garden. */
export const PLANT_STAGES = [
  "unassessed",
  "sprouting",
  "assisted",
  "independent",
  "transfer",
  "retained",
] as const;
export type PlantStage = (typeof PLANT_STAGES)[number];

export * from "./identity";
export * from "./garden";
