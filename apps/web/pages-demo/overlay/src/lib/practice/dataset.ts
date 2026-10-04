"use client";

import {
  DIMENSION_TO_PART,
  type Character,
  type EvidenceDimension,
  type EvidenceItem,
  type GardenDataset,
  type GrowthEvent,
  type LiveGrowthEvent,
  type MemoryItem,
  type PlantStage,
  type SessionMarker,
} from "@sg/contracts";
import { useSyncExternalStore } from "react";

import { DAY_MS, plantsAt } from "@/lib/garden/derive";
import { buildMockDataset } from "@/lib/garden/mock";
import { DEFAULT_STATE } from "@/lib/garden/state";

import { broadcastGrowth } from "./live";
import {
  newId,
  readRecords,
  recordsVersion,
  subscribeRecords,
  updateRecords,
  type PracticeRecords,
} from "./store";

/**
 * The garden on this site: the sample learner's history, re-dated to today, plus everything
 * practised in this browser. Practice adds evidence exactly like the full app's judge does, and
 * the garden is derived from evidence alone, so a plant grows only from what was demonstrated.
 */
export const RULES_VERSION = "rules@1+normal.1";
export const RUBRIC_VERSION = "cs-core@v1/rubric.1";

/** Credit per judged outcome, as in `rules/profile.yaml` (`outcome_credit`). */
const CREDIT = { demonstrated: 0.9, partial: 0.5 } as const;

function resolveMemory(records: PracticeRecords, memory: MemoryItem): MemoryItem {
  let current = memory;
  // Each correction is keyed by the id it replaced; follow the chain to the latest wording.
  for (let i = 0; i < 20 && records.memoryEdits[current.id]; i++) {
    current = records.memoryEdits[current.id]!;
  }
  return current;
}

export function buildPracticeDataset(now: Date, records: PracticeRecords): GardenDataset {
  const base = buildMockDataset(now);
  const nowMs = now.getTime();
  const byTime = <T extends { occurredAt: string }>(a: T, b: T) =>
    a.occurredAt.localeCompare(b.occurredAt);
  const deleted = new Set(records.deletedMemories);
  const memories = [...base.memories, ...records.memories]
    .map((m) => ({ original: m.id, item: resolveMemory(records, m) }))
    .filter(({ original, item }) => !deleted.has(original) && !deleted.has(item.id))
    .map(({ item }) => item);
  const today = Math.floor(nowMs / DAY_MS);
  const practisedToday = records.sessions.some(
    (s) => Math.floor(Date.parse(s.startedAt) / DAY_MS) === today,
  );

  return {
    ...base,
    freshness: { ...base.freshness, rulesVersion: RULES_VERSION },
    evidence: [
      ...base.evidence,
      ...records.evidence.filter((e) => Date.parse(e.occurredAt) <= nowMs),
    ].sort(byTime),
    growthEvents: [...base.growthEvents, ...records.growthEvents].sort(byTime),
    sessions: [...base.sessions, ...records.sessions].sort((a, b) =>
      a.startedAt.localeCompare(b.startedAt),
    ),
    memories,
    misconceptions: [...base.misconceptions, ...records.misconceptions],
    streakDays: base.streakDays + (practisedToday ? 1 : 0),
  };
}

let snapshot: { version: number; dataset: GardenDataset } | null = null;

function currentDataset(): GardenDataset {
  const version = recordsVersion();
  if (!snapshot || snapshot.version !== version) {
    snapshot = { version, dataset: buildPracticeDataset(new Date(), readRecords()) };
  }
  return snapshot.dataset;
}

/** The learner's garden, rebuilt whenever practice is saved (in this tab or another). */
export function usePracticeDataset(): GardenDataset {
  return useSyncExternalStore(subscribeRecords, currentDataset, currentDataset);
}

export const getPracticeDataset = currentDataset;

// ─── Recording practice ────────────────────────────────────────────────────────────────────

export type Outcome = "demonstrated" | "partial";

/** One judged answer that earns evidence. */
export interface EvidenceDraft {
  plantKey: string;
  dimension: EvidenceDimension;
  kind: "independent" | "assisted";
  outcome: Outcome;
  /** The learner's own words or code: shown as a quote, never interpreted. */
  quote: string;
  source: EvidenceItem["source"];
  rationale: string;
  assistNote?: string;
  confidence: number;
}

export interface PracticeOutcome {
  character: Character;
  title: string;
  startedAt: number;
  endedAt: number;
  evidence: EvidenceDraft[];
  memories?: Pick<MemoryItem, "layer" | "text" | "why" | "affects">[];
}

export interface RecordedPractice {
  sessionId: string;
  evidence: EvidenceItem[];
  growth: GrowthEvent[];
  saved: boolean;
}

const stageOfPlant = (dataset: GardenDataset, key: string, cutoff: number): PlantStage =>
  plantsAt(dataset, DEFAULT_STATE.filters, cutoff).find((p) => p.meta.key === key)?.stage ??
  "unassessed";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const clip = (s: string, n: number) => {
  const flat = s.replace(/\s+/g, " ").trim();
  return flat.length <= n ? flat : `${flat.slice(0, n - 1).trimEnd()}…`;
};

/** Save a finished session: its evidence, the growth that evidence causes, and the session. */
export function recordPractice(outcome: PracticeOutcome): RecordedPractice {
  const sessionId = newId("ses");
  const end = Math.max(outcome.endedAt, outcome.startedAt);
  let dataset = buildPracticeDataset(new Date(end), readRecords());
  let revision = dataset.growthEvents.reduce((max, g) => Math.max(max, g.revision), 0);
  const known = new Set(dataset.plants.map((p) => p.key));
  const drafts = outcome.evidence.filter((d) => known.has(d.plantKey));
  const evidence: EvidenceItem[] = [];
  const growth: GrowthEvent[] = [];

  drafts.forEach((d, i) => {
    // Spread the items over the last seconds of the session so their order is kept.
    const occurredAt = new Date(end - (drafts.length - i) * 1000).toISOString();
    const item: EvidenceItem = {
      id: newId("ev"),
      plantKey: d.plantKey,
      dimension: d.dimension,
      kind: d.kind,
      character: outcome.character,
      sessionId,
      occurredAt,
      quote: clip(d.quote, 280),
      source: d.source,
      rationale: d.rationale,
      assistNote: d.kind === "assisted" ? d.assistNote : undefined,
      confidence: d.confidence,
      weight: CREDIT[d.outcome],
      rubricVersion: RUBRIC_VERSION,
      status: "confirmed",
    };
    const before = stageOfPlant(dataset, d.plantKey, end);
    dataset = { ...dataset, evidence: [...dataset.evidence, item] };
    const after = stageOfPlant(dataset, d.plantKey, end);
    const part = d.dimension === "communication" ? null : DIMENSION_TO_PART[d.dimension];
    revision += 1;
    evidence.push(item);
    growth.push({
      id: newId("gr"),
      plantKey: d.plantKey,
      occurredAt,
      dimension: d.dimension,
      fromStage: before,
      toStage: after,
      summary: `${part ? `${cap(part)} grew` : "Communication noted"}${
        d.kind === "assisted" ? " (assisted, with hints)" : ""
      }`,
      evidenceIds: [item.id],
      revision,
    });
  });

  const session: SessionMarker = {
    id: sessionId,
    character: outcome.character,
    startedAt: new Date(outcome.startedAt).toISOString(),
    minutes: Math.max(1, Math.round((end - outcome.startedAt) / 60_000)),
    title: outcome.title,
    evidenceIds: evidence.map((e) => e.id),
  };
  const memories: MemoryItem[] = (outcome.memories ?? []).map((m) => ({
    id: newId("mem"),
    character: outcome.character,
    layer: m.layer,
    text: m.text,
    why: m.why,
    status: "accepted",
    confidence: 0.9,
    evidenceIds: evidence.map((e) => e.id).slice(0, 3),
    affects: m.affects,
    deletable: m.layer === "private",
    createdAt: new Date(end).toISOString(),
  }));

  const saved = updateRecords((r) => ({
    ...r,
    evidence: [...r.evidence, ...evidence],
    growthEvents: [...r.growthEvents, ...growth],
    sessions: [...r.sessions, session],
    memories: [...r.memories, ...memories],
  }));

  for (const item of evidence) broadcastGrowth(toLiveEvent(item, "confirmed"));
  return { sessionId, evidence, growth, saved };
}

/** The live event a garden glows for while an answer is judged (and when it is confirmed). */
export function toLiveEvent(
  item: Pick<EvidenceItem, "plantKey" | "dimension" | "kind" | "quote" | "sessionId">,
  kind: LiveGrowthEvent["kind"],
  outcome: LiveGrowthEvent["outcome"] = "demonstrated",
): LiveGrowthEvent {
  return {
    id: newId("live"),
    kind,
    sessionId: item.sessionId,
    conceptId: item.plantKey,
    questionId: null,
    dimension: item.dimension,
    part: item.dimension === "communication" ? null : DIMENSION_TO_PART[item.dimension],
    outcome,
    assisted: item.kind === "assisted",
    quote: clip(item.quote, 160),
    note: "",
    judge: "rubric",
    reason: "",
    occurredAt: new Date().toISOString(),
  };
}
