import {
  DIMENSION_TO_PART,
  type Dimension,
  type DimensionScore,
  type EvidenceItem,
  type GardenSnapshot,
  type Grove,
  type PlantPart,
  type PlantSnapshot,
  type PlantState,
  type PrerequisiteEdge,
} from "@sg/contracts";

import { PART_TO_DIMENSION } from "./growth";
import type { EvidenceCardData } from "./types";

/**
 * Adapters between the dashboard's view model (`PlantState`, filtered and time-travelled in the
 * browser) and what the scene renders (`GardenSnapshot`, `EvidenceCardData`). Pure, so the
 * dashboard and tests share one mapping. The scene is keyed by concept key (`dsa.bfs`), which is
 * also the dashboard's plant key and the API's `conceptId`.
 */

const DIMENSIONS = Object.keys(DIMENSION_TO_PART) as Dimension[];

export interface SnapshotInput {
  groves: readonly Grove[];
  plants: readonly PlantState[];
  prerequisites?: readonly PrerequisiteEdge[];
  /** ISO timestamp the state is as of. */
  asOf: string;
  /** Latest garden revision visible at `asOf` (0 when nothing has grown yet). */
  revision: number;
  ruleVersion: string;
}

/** The scene snapshot for the dashboard's current view. Assisted scores stay separate. */
export function snapshotFromPlants(input: SnapshotInput): GardenSnapshot {
  const known = new Set(input.plants.map((p) => p.meta.key));
  const plants: PlantSnapshot[] = input.plants.map((p) => {
    const dimensions = Object.fromEntries(
      DIMENSIONS.map((d): [Dimension, DimensionScore] => [
        d,
        { independent: p.independent[d] ?? 0, assisted: p.assisted[d] ?? 0 },
      ]),
    ) as Record<Dimension, DimensionScore>;
    return {
      conceptId: p.meta.key,
      groveId: p.meta.grove,
      label: p.meta.title,
      status: p.wilting ? "wilting" : p.stage,
      dimensions,
      evidenceCount: p.evidenceCount.independent + p.evidenceCount.assisted,
      lastEvidenceAt: p.lastEvidenceAt,
      nextReviewAt: p.nextReviewAt,
    };
  });
  return {
    revision: input.revision,
    ruleVersion: input.ruleVersion,
    createdAt: input.asOf,
    groves: input.groves.map((g) => ({ id: g.id, label: g.title })),
    plants,
    prerequisites: (input.prerequisites ?? []).filter((e) => known.has(e.from) && known.has(e.to)),
  };
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const CARD_KIND = { transcript: "transcript", code: "code", tests: "test" } as const;

/** Evidence cards for one plant part: the learner's own evidence, newest first, at most `limit`. */
export function evidenceCardsFor(
  evidence: readonly EvidenceItem[],
  conceptId: string,
  part: PlantPart,
  limit = 6,
): EvidenceCardData[] {
  const dimension = PART_TO_DIMENSION[part];
  return evidence
    .filter((e) => e.plantKey === conceptId && e.dimension === dimension)
    .toSorted((a, b) => b.occurredAt.localeCompare(a.occurredAt))
    .slice(0, limit)
    .map((e) => ({
      id: e.id,
      dimension,
      kind: CARD_KIND[e.source],
      character: e.character,
      title: `${cap(e.character)} · ${e.kind}`,
      excerpt: e.quote,
      occurredAt: e.occurredAt,
      independent: e.kind === "independent",
      uncertainty: Math.round((1 - e.confidence) * 100) / 100,
      rubricVersion: e.rubricVersion,
    }));
}
