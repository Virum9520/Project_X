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

/**
 * Every status a plant can hold. The first six are the growth stages above; `due` and `wilting`
 * mark plants whose spaced-repetition review is due or overdue. Mirrors `PlantStatus` in
 * `sg_core.models.enums` (a test enforces it).
 */
export const PLANT_STATUSES = [...PLANT_STAGES, "due", "wilting"] as const;
export type PlantStatus = (typeof PLANT_STATUSES)[number];

/**
 * Garden snapshot: the read model the garden scene renders (C13) and the analytics API serves
 * (C14). One snapshot is the projected state of a learner's garden at one `garden_revisions.rev`.
 */

/** Scores for one dimension, each in [0, 1]. Assisted evidence never counts as independent. */
export interface DimensionScore {
  independent: number;
  assisted: number;
}

/** A domain cluster of concepts (DSA, OS, networks, ...). */
export interface GroveSnapshot {
  id: string;
  label: string;
}

/** One concept plant. The snapshot lists every curriculum concept, unassessed ones included. */
export interface PlantSnapshot {
  conceptId: string;
  groveId: string;
  label: string;
  status: PlantStatus;
  dimensions: Record<Dimension, DimensionScore>;
  /** Live, not-yet-confirmed growth from an in-progress session (SSE), per dimension in [0, 1]. */
  provisional?: Partial<Record<Dimension, number>>;
  /** Number of evidence items backing this plant's growth. */
  evidenceCount: number;
  /** ISO 8601 timestamps. */
  lastEvidenceAt?: string | null;
  nextReviewAt?: string | null;
}

/** `to` depends on `from`: the garden draws a glowing root path from `from` to `to`. */
export interface PrerequisiteEdge {
  from: string;
  to: string;
}

export interface GardenSnapshot {
  revision: number;
  ruleVersion: string;
  /** ISO 8601 timestamp of the revision. */
  createdAt: string;
  groves: GroveSnapshot[];
  plants: PlantSnapshot[];
  prerequisites: PrerequisiteEdge[];
}

export * from "./identity";
export * from "./admin";
export * from "./garden";
export * from "./future-self";
export * from "./session";
export * from "./arjuna";
