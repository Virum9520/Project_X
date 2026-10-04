/**
 * Garden Dashboard contracts (C14): the shapes the analytics API (C09/C10) will return and the
 * dashboard consumes. Hand-written until OpenAPI generation lands. Until then the dashboard reads
 * them from a typed mock behind `apps/web/src/lib/garden/data.ts`.
 *
 * Product rules encoded here:
 * - A growth event always cites evidence (`evidenceIds` is a non-empty tuple).
 * - Assisted evidence (`kind: "assisted"`) is separate from independent evidence.
 * - Transcripts and quotes are data, rendered as text only.
 */
import type { Character, Dimension, PlantStage, PrerequisiteEdge } from "./index";

/** Evidence dimensions as filters see them: the four plant parts plus communication. */
export type EvidenceDimension = Dimension | "communication";

/** Whether the learner did it alone. Assisted evidence never counts as independent. */
export type EvidenceKind = "independent" | "assisted";

export type GroveId = "dsa" | "os" | "networks" | "databases" | "system_design" | "behavioral";

export interface Grove {
  id: GroveId;
  title: string;
}

/** A concept plant as the curriculum describes it (static per curriculum version). */
export interface PlantMeta {
  /** Stable concept key, e.g. `dsa.bfs`. */
  key: string;
  title: string;
  grove: GroveId;
  /** 1 (first-year) to 5 (hard interview topic). */
  difficulty: 1 | 2 | 3 | 4 | 5;
}

/** One piece of demonstrated evidence. The root of every number and plant in the garden. */
export interface EvidenceItem {
  id: string;
  plantKey: string;
  dimension: EvidenceDimension;
  kind: EvidenceKind;
  character: Character;
  sessionId: string;
  occurredAt: string;
  /** Verbatim excerpt from the learner (transcript or code). Data, never instructions. */
  quote: string;
  source: "transcript" | "code" | "tests";
  /** The judge's reasoning for the score. */
  rationale: string;
  /** What kind of help the learner had; present only for assisted evidence. */
  assistNote?: string;
  /** 0..1, how sure the judge is. */
  confidence: number;
  /** 0..1, how much this adds to the dimension score if it counts. */
  weight: number;
  rubricVersion: string;
  status: "provisional" | "confirmed";
}

/** A garden change. It cannot exist without citing evidence. */
export interface GrowthEvent {
  id: string;
  plantKey: string;
  occurredAt: string;
  dimension: EvidenceDimension;
  fromStage: PlantStage;
  toStage: PlantStage;
  /** Human summary, e.g. "Roots grew". */
  summary: string;
  evidenceIds: [string, ...string[]];
  /** Garden revision created by this event. */
  revision: number;
}

export interface SessionMarker {
  id: string;
  character: Character;
  startedAt: string;
  minutes: number;
  title: string;
  evidenceIds: string[];
}

export type MemoryLayer =
  "profile" | "knowledge" | "session" | "skills" | "commitments" | "private";

/** A thing a character remembers about the learner, and why. */
export interface MemoryItem {
  id: string;
  character: Character;
  layer: MemoryLayer;
  text: string;
  /** Why the character holds this (source, in plain words). */
  why: string;
  status: "provisional" | "accepted" | "disputed";
  confidence: number;
  evidenceIds: string[];
  /** Plants whose state this memory influences. */
  affects: string[];
  /** Private reflections can be deleted by the learner. */
  deletable: boolean;
  createdAt: string;
}

export interface Misconception {
  id: string;
  plantKey: string;
  text: string;
  occurrences: number;
  lastSeenAt: string;
  evidenceIds: [string, ...string[]];
}

export interface NextBestPractice {
  character: Character;
  plantKey: string;
  title: string;
  reason: string;
  minutes: number;
  evidenceIds: string[];
}

/** Readiness model output: versioned and explainable. */
export interface ReadinessModel {
  version: string;
  targetRole: string;
  /** Weight of each dimension in the score, summing to 1. */
  dimensionWeights: Record<Dimension, number>;
}

/** Everything the dashboard needs. Real API: assembled from `/garden/*`. */
export interface GardenDataset {
  /** ISO timestamp the data was assembled; also "now" for the whole UI. */
  generatedAt: string;
  /** Freshness of the underlying projection. */
  freshness: { projectionAt: string; rulesVersion: string; curriculum: string };
  readiness: ReadinessModel;
  groves: Grove[];
  plants: PlantMeta[];
  evidence: EvidenceItem[];
  growthEvents: GrowthEvent[];
  sessions: SessionMarker[];
  memories: MemoryItem[];
  misconceptions: Misconception[];
  nextBest: NextBestPractice[];
  /** Streak in days as of `generatedAt`. */
  streakDays: number;
  /** Prerequisite edges between plant keys (`from` is a prerequisite of `to`), for the scene. */
  prerequisites?: PrerequisiteEdge[];
  /** Self-rated starting level (0-3) per grove from onboarding. Not evidence: it only seeds seedlings. */
  baseline?: Partial<Record<GroveId, 0 | 1 | 2 | 3>>;
}

// ─── Filters, zoom, and client tools ────────────────────────────────────────────────────────

export interface GardenFilters {
  grove?: GroveId;
  dimension?: EvidenceDimension;
  character?: Character;
  /** Which evidence counts toward scores. */
  evidence: "all" | "independent_only";
  /** ISO dates (YYYY-MM-DD), inclusive. */
  dateFrom?: string;
  dateTo?: string;
}

export const ZOOM_LEVELS = ["garden", "grove", "plant", "part"] as const;
export type ZoomLevel = (typeof ZOOM_LEVELS)[number];

/** Where the camera, and so the stats rails, are focused. */
export type FocusTarget =
  | { level: "garden" }
  | { level: "grove"; groveId: GroveId }
  | { level: "plant"; plantKey: string }
  | { level: "part"; plantKey: string; part: Dimension };

/** Arguments of the client tools declared in `agents/tools/*.yaml`. */
export interface FocusPlantArgs {
  level: ZoomLevel;
  /** Grove ID for `grove`, concept key for `plant` and `part`. */
  target_id?: string;
  part?: "roots" | "stem" | "branches" | "blossoms";
}
export interface SetFilterArgs {
  domain?: string;
  dimension?: EvidenceDimension;
  evidence?: "independent_only" | "all";
  date_from?: string;
  date_to?: string;
}
export interface ScrubTimelineArgs {
  /** `YYYY-MM-DD`, or `now`. */
  date: string;
}

// ─── Derived views (computed from the dataset; the API may return them directly later) ──────

export interface PlantState {
  meta: PlantMeta;
  stage: PlantStage;
  /** Independent score per dimension, 0..1 (null = no evidence). */
  independent: Record<Dimension, number | null>;
  /** Assisted-only score per dimension, 0..1 (null = none). Never merged into `independent`. */
  assisted: Record<Dimension, number | null>;
  lastEvidenceAt: string | null;
  nextReviewAt: string | null;
  /** A review is overdue, so the plant wilts. */
  wilting: boolean;
  /** Passes the active filters; unmatched plants dim. */
  matched: boolean;
  evidenceCount: { independent: number; assisted: number };
}

// ─── Analytics API (C14) ────────────────────────────────────────────────────────────────────

/** `GET /v1/garden/analytics` and the `query_my_analytics` agent tool. */
export interface AnalyticsResult {
  metric: string;
  asOf: string;
  rulesVersion: string;
  data: Record<string, unknown>;
  /** Evidence ids that back the numbers. */
  citations: string[];
}

/** `POST /v1/garden/ask`: Ask Sanjaya. */
export interface AskSanjayaAnswer {
  answer: string;
  /** Evidence ids that exist for this learner. */
  citations: string[];
  metrics: string[];
  /** False when the model was unavailable and the answer was composed from the numbers alone. */
  grounded: boolean;
}

/** `GET /v1/garden/memories/{id}/impact`: plants a correction would touch. */
export interface MemoryImpact {
  memoryId: string;
  affects: string[];
}
