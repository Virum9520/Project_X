/**
 * Pure derivations from a `GardenDataset`: plant state at a point in time, stage counts,
 * readiness, review backlog and timeline series. No I/O, no clock reads, so everything is
 * deterministic and replayable.
 *
 * NOTE: the real rules engine (C10) owns persistent garden state. This module mirrors its shape
 * so the UI can run on mocks; when the analytics API lands, `plantsAt` is replaced by the API's
 * garden-at-revision response and the rest keeps working.
 */
import {
  DIMENSION_TO_PART,
  PLANT_STAGES,
  type Dimension,
  type EvidenceItem,
  type GardenDataset,
  type GardenFilters,
  type GroveId,
  type PlantStage,
  type PlantState,
} from "@sg/contracts";

export const DIMENSIONS = Object.keys(DIMENSION_TO_PART) as Dimension[];
export const DAY_MS = 86_400_000;

/** Days until a plant needs another independent demonstration, by stage. */
const REVIEW_INTERVAL_DAYS: Record<PlantStage, number | null> = {
  unassessed: null,
  sprouting: 4,
  assisted: 4,
  independent: 7,
  transfer: 14,
  retained: 30,
};

export const endOfDay = (isoDate: string) => Date.parse(`${isoDate}T23:59:59.999Z`);
export const toIsoDate = (ms: number) => new Date(ms).toISOString().slice(0, 10);

/** The instant the garden is viewed at: the scrubber date, bounded by the date-range filter. */
export function cutoffMs(dataset: GardenDataset, scrubDate: string | null, f: GardenFilters) {
  let cutoff = Date.parse(dataset.generatedAt);
  if (scrubDate) cutoff = Math.min(cutoff, endOfDay(scrubDate));
  if (f.dateTo) cutoff = Math.min(cutoff, endOfDay(f.dateTo));
  return cutoff;
}

/** Evidence that is visible under the filters at `cutoff`. */
export function visibleEvidence(
  dataset: GardenDataset,
  f: GardenFilters,
  cutoff: number,
): EvidenceItem[] {
  const from = f.dateFrom ? Date.parse(`${f.dateFrom}T00:00:00.000Z`) : -Infinity;
  const groveOf = new Map(dataset.plants.map((p) => [p.key, p.grove]));
  return dataset.evidence.filter((e) => {
    const t = Date.parse(e.occurredAt);
    if (t > cutoff || t < from) return false;
    if (f.evidence === "independent_only" && e.kind !== "independent") return false;
    if (f.dimension && e.dimension !== f.dimension) return false;
    if (f.character && e.character !== f.character) return false;
    if (f.grove && groveOf.get(e.plantKey) !== f.grove) return false;
    return true;
  });
}

const emptyScores = (): Record<Dimension, number | null> => ({
  explanation: null,
  application: null,
  transfer: null,
  retention: null,
});

const isScored = (d: EvidenceItem["dimension"]): d is Dimension => d !== "communication";

/** Replay a plant's evidence into scores and a stage. */
export function stageOf(ind: Record<Dimension, number | null>, hasAny: boolean, hasInd: boolean) {
  const s = (d: Dimension) => ind[d] ?? 0;
  if (!hasAny) return "unassessed" as const;
  if (s("retention") >= 0.5) return "retained" as const;
  if (s("transfer") >= 0.5) return "transfer" as const;
  if (s("explanation") >= 0.6 && s("application") >= 0.5) return "independent" as const;
  return hasInd ? ("sprouting" as const) : ("assisted" as const);
}

/** Garden state at `cutoff` under `filters`. Scores come only from the visible evidence. */
export function plantsAt(
  dataset: GardenDataset,
  filters: GardenFilters,
  cutoff: number,
): PlantState[] {
  const visible = visibleEvidence(dataset, { ...filters, grove: undefined }, cutoff);
  const byPlant = Map.groupBy(visible, (e) => e.plantKey);
  const evidenceLevelFilter = Boolean(
    filters.dimension || filters.character || filters.dateFrom || filters.dateTo,
  );

  return dataset.plants.map((meta) => {
    const items = byPlant.get(meta.key) ?? [];
    const independent = emptyScores();
    const assisted = emptyScores();
    let lastEvidenceAt: number | null = null;
    let lastIndependentAt: number | null = null;
    const count = { independent: 0, assisted: 0 };

    for (const e of items) {
      const t = Date.parse(e.occurredAt);
      lastEvidenceAt = Math.max(lastEvidenceAt ?? t, t);
      count[e.kind] += 1;
      if (e.kind === "independent") lastIndependentAt = Math.max(lastIndependentAt ?? t, t);
      if (!isScored(e.dimension)) continue;
      const bucket = e.kind === "independent" ? independent : assisted;
      bucket[e.dimension] = Math.min(1, (bucket[e.dimension] ?? 0) + e.weight * e.confidence);
    }

    let baselineLevel: PlantState["baselineLevel"];
    let stage = stageOf(independent, items.length > 0, count.independent > 0);
    // A self-rated baseline plants a seedling where there is no evidence yet. It never raises
    // scores, readiness or review dates: only demonstrated evidence grows a plant further.
    const baseline = dataset.baseline?.[meta.grove] ?? 0;
    if (stage === "unassessed" && !evidenceLevelFilter && baseline > 0) {
      stage = "sprouting";
      baselineLevel = baseline as 1 | 2 | 3;
    }
    const interval = REVIEW_INTERVAL_DAYS[stage];
    const reviewBase = lastIndependentAt ?? lastEvidenceAt;
    const nextReviewMs = interval && reviewBase ? reviewBase + interval * DAY_MS : null;

    const inGrove = !filters.grove || meta.grove === filters.grove;
    return {
      meta,
      stage,
      independent,
      assisted,
      lastEvidenceAt: lastEvidenceAt ? new Date(lastEvidenceAt).toISOString() : null,
      nextReviewAt: nextReviewMs ? new Date(nextReviewMs).toISOString() : null,
      wilting: nextReviewMs !== null && nextReviewMs < cutoff,
      matched: inGrove && (!evidenceLevelFilter || items.length > 0),
      evidenceCount: count,
      baselineLevel,
    };
  });
}

export function stageCounts(plants: PlantState[]): Record<PlantStage, number> {
  const out = Object.fromEntries(PLANT_STAGES.map((s) => [s, 0])) as Record<PlantStage, number>;
  for (const p of plants) out[p.stage] += 1;
  return out;
}

/** Independent-evidence readiness, 0..100. Assisted evidence earns nothing here, by design. */
export function plantReadiness(p: PlantState, weights: Record<Dimension, number>) {
  return DIMENSIONS.reduce((sum, d) => sum + weights[d] * (p.independent[d] ?? 0), 0);
}

export interface Readiness {
  overall: number;
  byGrove: { grove: GroveId; score: number; plants: number }[];
}

export function readiness(
  dataset: GardenDataset,
  plants: PlantState[],
  groves: GroveId[] = dataset.groves.map((g) => g.id),
): Readiness {
  const byGrove = groves.map((grove) => {
    const inGrove = plants.filter((p) => p.meta.grove === grove);
    const score = inGrove.length
      ? (inGrove.reduce((s, p) => s + plantReadiness(p, dataset.readiness.dimensionWeights), 0) /
          inGrove.length) *
        100
      : 0;
    return { grove, score, plants: inGrove.length };
  });
  const populated = byGrove.filter((g) => g.plants > 0);
  const overall = populated.length
    ? populated.reduce((s, g) => s + g.score, 0) / populated.length
    : 0;
  return { overall, byGrove };
}

export interface ReviewStats {
  dueSoon: number;
  overdue: number;
}

export function reviewStats(plants: PlantState[], cutoff: number): ReviewStats {
  let dueSoon = 0;
  let overdue = 0;
  for (const p of plants) {
    if (!p.nextReviewAt) continue;
    const due = Date.parse(p.nextReviewAt);
    if (due < cutoff) overdue += 1;
    else if (due < cutoff + 3 * DAY_MS) dueSoon += 1;
  }
  return { dueSoon, overdue };
}

export function independentRatio(plants: PlantState[]) {
  const independent = plants.reduce((s, p) => s + p.evidenceCount.independent, 0);
  const assisted = plants.reduce((s, p) => s + p.evidenceCount.assisted, 0);
  const total = independent + assisted;
  return { independent, assisted, share: total ? independent / total : null };
}

export interface TimelinePoint {
  date: string;
  counts: Record<PlantStage, number>;
}

/** Stage counts per day (the shape of a continuous aggregate), for the growth chart. */
export function timelineSeries(
  dataset: GardenDataset,
  filters: GardenFilters,
  endMs: number,
  days: number,
): TimelinePoint[] {
  const points: TimelinePoint[] = [];
  const evidenceFiltersOnly = { ...filters, dateFrom: undefined, dateTo: undefined };
  for (let i = days - 1; i >= 0; i--) {
    const day = toIsoDate(endMs - i * DAY_MS);
    const cutoff = Math.min(endMs, endOfDay(day));
    const plants = plantsAt(dataset, evidenceFiltersOnly, cutoff).filter(
      (p) => !filters.grove || p.meta.grove === filters.grove,
    );
    points.push({ date: day, counts: stageCounts(plants) });
  }
  return points;
}

export function hoursPracticed(dataset: GardenDataset, cutoff: number, days = 7) {
  const from = cutoff - days * DAY_MS;
  const minutes = dataset.sessions
    .filter((s) => {
      const t = Date.parse(s.startedAt);
      return t >= from && t <= cutoff;
    })
    .reduce((sum, s) => sum + s.minutes, 0);
  return minutes / 60;
}

export const stageRank = (s: PlantStage) => PLANT_STAGES.indexOf(s);
