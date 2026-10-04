import {
  DIMENSION_TO_PART,
  type Character,
  type Dimension,
  type DimensionScore,
  type GardenSnapshot,
  type PlantPart,
  type PlantSnapshot,
  type PlantStatus,
  type PrerequisiteEdge,
} from "@sg/contracts";

import { createRng, range } from "../generator/random";
import { PART_TO_DIMENSION } from "../model/growth";
import type { EvidenceCardData } from "../model/types";

/**
 * Mock garden for building the scene before the real pipeline exists (C07 curriculum, C10 rules
 * engine, C14 analytics API). Concept ids and statuses here are illustrative only. The real
 * curriculum and the deterministic rules engine replace them.
 *
 * The history is a seeded "demo learner": a half-grown garden over 16 revisions, with a few
 * plants due for review or wilting at the end, matching the demo seed described in the build plan.
 */

const GROVES: { id: string; label: string; concepts: [string, string][] }[] = [
  {
    id: "dsa",
    label: "Data Structures & Algorithms",
    concepts: [
      ["arrays", "Arrays & Strings"],
      ["hashing", "Hash Maps"],
      ["two-pointers", "Two Pointers"],
      ["stacks-queues", "Stacks & Queues"],
      ["linked-lists", "Linked Lists"],
      ["trees", "Binary Trees"],
      ["binary-search", "Binary Search"],
      ["graphs", "Graphs (BFS/DFS)"],
      ["heaps", "Heaps"],
      ["dynamic-programming", "Dynamic Programming"],
    ],
  },
  {
    id: "os",
    label: "Operating Systems",
    concepts: [
      ["processes", "Processes & Threads"],
      ["scheduling", "CPU Scheduling"],
      ["synchronization", "Locks & Synchronization"],
      ["deadlocks", "Deadlocks"],
      ["virtual-memory", "Virtual Memory"],
      ["file-systems", "File Systems"],
    ],
  },
  {
    id: "networks",
    label: "Networks",
    concepts: [
      ["layers", "TCP/IP Layers"],
      ["tcp-udp", "TCP vs UDP"],
      ["dns", "DNS"],
      ["http", "HTTP"],
      ["tls", "TLS"],
      ["load-balancing", "Load Balancing"],
    ],
  },
  {
    id: "databases",
    label: "Databases",
    concepts: [
      ["relational", "Relational Model"],
      ["sql-joins", "SQL Joins"],
      ["indexing", "Indexing"],
      ["transactions", "Transactions & ACID"],
      ["normalization", "Normalization"],
      ["nosql", "NoSQL Trade-offs"],
    ],
  },
  {
    id: "system_design",
    label: "System Design",
    concepts: [
      ["scalability", "Scalability Basics"],
      ["caching", "Caching"],
      ["sharding", "Sharding"],
      ["queues", "Message Queues"],
      ["consistency", "Consistency & CAP"],
      ["rate-limiting", "Rate Limiting"],
    ],
  },
  {
    id: "behavioral",
    label: "Behavioral",
    concepts: [
      ["star", "STAR Stories"],
      ["ownership", "Ownership"],
      ["conflict", "Handling Conflict"],
      ["failure", "Learning from Failure"],
      ["leadership", "Leadership"],
    ],
  },
];

const EDGES: [string, string][] = [
  ["dsa.arrays", "dsa.hashing"],
  ["dsa.arrays", "dsa.two-pointers"],
  ["dsa.arrays", "dsa.stacks-queues"],
  ["dsa.arrays", "dsa.binary-search"],
  ["dsa.linked-lists", "dsa.trees"],
  ["dsa.stacks-queues", "dsa.graphs"],
  ["dsa.trees", "dsa.graphs"],
  ["dsa.trees", "dsa.heaps"],
  ["dsa.hashing", "dsa.dynamic-programming"],
  ["dsa.graphs", "dsa.dynamic-programming"],
  ["os.processes", "os.scheduling"],
  ["os.processes", "os.synchronization"],
  ["os.synchronization", "os.deadlocks"],
  ["os.processes", "os.virtual-memory"],
  ["os.virtual-memory", "os.file-systems"],
  ["networks.layers", "networks.tcp-udp"],
  ["networks.tcp-udp", "networks.http"],
  ["networks.layers", "networks.dns"],
  ["networks.http", "networks.tls"],
  ["networks.http", "networks.load-balancing"],
  ["databases.relational", "databases.sql-joins"],
  ["databases.relational", "databases.normalization"],
  ["databases.sql-joins", "databases.indexing"],
  ["databases.relational", "databases.transactions"],
  ["databases.indexing", "databases.nosql"],
  ["system_design.scalability", "system_design.caching"],
  ["system_design.scalability", "system_design.sharding"],
  ["system_design.scalability", "system_design.queues"],
  ["system_design.sharding", "system_design.consistency"],
  ["system_design.caching", "system_design.rate-limiting"],
  ["behavioral.star", "behavioral.ownership"],
  ["behavioral.star", "behavioral.conflict"],
  ["behavioral.star", "behavioral.failure"],
  ["behavioral.ownership", "behavioral.leadership"],
  // Cross-domain roots.
  ["dsa.hashing", "system_design.caching"],
  ["dsa.trees", "databases.indexing"],
  ["dsa.stacks-queues", "system_design.queues"],
  ["os.synchronization", "databases.transactions"],
  ["networks.load-balancing", "system_design.scalability"],
  ["databases.transactions", "system_design.consistency"],
];

export const MOCK_REVISIONS = 16;
const RULE_VERSION = "profile@mock";
const START = Date.UTC(2026, 8, 1, 15, 0, 0);
const DAY = 24 * 60 * 60 * 1000;

/** Final status each mock concept ends the history on. */
type Target = PlantStatus;

/** Final stage per concept: a deterministic mix that exercises every visual state. */
const TARGET_MIX: Target[] = [
  "retained",
  "transfer",
  "independent",
  "assisted",
  "sprouting",
  "unassessed",
  "transfer",
  "independent",
  "due",
  "retained",
  "assisted",
  "wilting",
  "independent",
  "sprouting",
  "unassessed",
];

interface Step {
  revision: number;
  dimension: Dimension;
  independent: number;
  assisted: number;
}

const DIMENSIONS: Dimension[] = ["explanation", "application", "transfer", "retention"];

function finalScores(target: Target, rng: () => number): Record<Dimension, DimensionScore> {
  const zero = { independent: 0, assisted: 0 };
  const solid = () => ({ independent: range(rng, 0.65, 0.95), assisted: range(rng, 0.2, 0.6) });
  const ghost = () => ({ independent: range(rng, 0, 0.15), assisted: range(rng, 0.4, 0.7) });
  const s: Record<Dimension, DimensionScore> = {
    explanation: zero,
    application: zero,
    transfer: zero,
    retention: zero,
  };
  switch (target) {
    case "unassessed":
      return s;
    case "sprouting":
      return { ...s, explanation: { independent: 0, assisted: range(rng, 0.25, 0.45) } };
    case "assisted":
      return { ...s, explanation: ghost(), application: ghost() };
    case "independent":
      return { ...s, explanation: solid(), application: solid(), transfer: ghost() };
    case "transfer":
      return { ...s, explanation: solid(), application: solid(), transfer: solid() };
    case "retained":
    case "due":
      return {
        explanation: solid(),
        application: solid(),
        transfer: solid(),
        retention: solid(),
      };
    case "wilting":
      return {
        explanation: solid(),
        application: solid(),
        transfer: ghost(),
        retention: { independent: range(rng, 0.3, 0.5), assisted: 0.2 },
      };
  }
}

/** Mock stand-in for the rules engine's status projection (C10 owns the real one). */
function deriveStatus(dimensions: Record<Dimension, DimensionScore>): PlantStatus {
  const { explanation: e, application: a, transfer: t, retention: r } = dimensions;
  if (DIMENSIONS.every((d) => dimensions[d].independent === 0 && dimensions[d].assisted === 0)) {
    return "unassessed";
  }
  if (r.independent >= 0.5) return "retained";
  if (t.independent >= 0.5) return "transfer";
  if (e.independent >= 0.5 || a.independent >= 0.5) return "independent";
  if (e.assisted >= 0.4 || a.assisted >= 0.4) return "assisted";
  return "sprouting";
}

interface MockConcept {
  conceptId: string;
  groveId: string;
  label: string;
  target: Target;
  steps: Step[];
}

function buildConcepts(): MockConcept[] {
  const concepts: MockConcept[] = [];
  let index = 0;
  for (const grove of GROVES) {
    for (const [slug, label] of grove.concepts) {
      const conceptId = `${grove.id}.${slug}`;
      const rng = createRng(`mock:${conceptId}`);
      const target = TARGET_MIX[index++ % TARGET_MIX.length] ?? "unassessed";
      const scores = finalScores(target, rng);
      const steps: Step[] = [];
      let revision = 1 + Math.floor(range(rng, 0, 7));
      for (const dimension of DIMENSIONS) {
        const score = scores[dimension];
        if (score.independent === 0 && score.assisted === 0) continue;
        // Each dimension grows in two sessions: a first attempt, then the final level.
        steps.push({
          revision: Math.min(MOCK_REVISIONS - 2, revision),
          dimension,
          independent: score.independent * 0.45,
          assisted: Math.max(score.assisted, score.independent * 0.6),
        });
        revision += 1 + Math.floor(range(rng, 0, 3));
        steps.push({ revision: Math.min(MOCK_REVISIONS - 1, revision), dimension, ...score });
        revision += Math.floor(range(rng, 0, 2));
      }
      concepts.push({ conceptId, groveId: grove.id, label, target, steps });
    }
  }
  return concepts;
}

const CONCEPTS = buildConcepts();

function plantAt(concept: MockConcept, revision: number): PlantSnapshot {
  const dimensions = Object.fromEntries(
    DIMENSIONS.map((d) => [d, { independent: 0, assisted: 0 }]),
  ) as Record<Dimension, DimensionScore>;
  let evidenceCount = 0;
  let last: number | null = null;
  for (const step of concept.steps) {
    if (step.revision > revision) continue;
    dimensions[step.dimension] = { independent: step.independent, assisted: step.assisted };
    evidenceCount += 2;
    last = Math.max(last ?? 0, step.revision);
  }
  let status = deriveStatus(dimensions);
  // Reviews come due at the end of the history for the due and wilting plants.
  if (concept.target === "due" && revision >= MOCK_REVISIONS - 1) status = "due";
  if (concept.target === "wilting" && revision >= MOCK_REVISIONS - 3) {
    status = revision >= MOCK_REVISIONS ? "wilting" : "due";
  }
  const reviewDays = status === "retained" ? 14 : 4;
  return {
    conceptId: concept.conceptId,
    groveId: concept.groveId,
    label: concept.label,
    status,
    dimensions,
    evidenceCount,
    lastEvidenceAt: last === null ? null : revisionDate(last),
    nextReviewAt:
      last === null
        ? null
        : new Date(
            status === "due" || status === "wilting"
              ? Date.parse(revisionDate(revision)) - DAY
              : Date.parse(revisionDate(last)) + reviewDays * DAY,
          ).toISOString(),
  };
}

function revisionDate(revision: number): string {
  return new Date(START + revision * 1.6 * DAY).toISOString();
}

/** The mock learner's garden at `revision` (0 = before any session, max `MOCK_REVISIONS`). */
export function mockGardenSnapshot(revision = MOCK_REVISIONS): GardenSnapshot {
  const rev = Math.max(0, Math.min(MOCK_REVISIONS, Math.round(revision)));
  const prerequisites: PrerequisiteEdge[] = EDGES.map(([from, to]) => ({ from, to }));
  return {
    revision: rev,
    ruleVersion: RULE_VERSION,
    createdAt: revisionDate(rev),
    groves: GROVES.map(({ id, label }) => ({ id, label })),
    plants: CONCEPTS.map((c) => plantAt(c, rev)),
    prerequisites,
  };
}

/** Every revision of the mock garden, oldest first. */
export function mockGardenHistory(): GardenSnapshot[] {
  return Array.from({ length: MOCK_REVISIONS + 1 }, (_, rev) => mockGardenSnapshot(rev));
}

/**
 * Simulates live provisional growth for one plant part, as an SSE update during a session would.
 * Returns a new snapshot; the input is not modified.
 */
export function withProvisionalGrowth(
  snapshot: GardenSnapshot,
  conceptId: string,
  dimension: Dimension,
  amount: number,
): GardenSnapshot {
  return {
    ...snapshot,
    plants: snapshot.plants.map((plant) =>
      plant.conceptId === conceptId
        ? { ...plant, provisional: { ...plant.provisional, [dimension]: amount } }
        : plant,
    ),
  };
}

const EXCERPTS: Record<Dimension, ((label: string) => [EvidenceCardData["kind"], string])[]> = {
  explanation: [
    (l) => [
      "transcript",
      `"So the key idea behind ${l} is the invariant we keep at every step..."`,
    ],
    (l) => ["transcript", `"If I explained ${l} to a first-year, I'd start with why it exists."`],
  ],
  application: [
    (l) => ["code", `def solve(nums):\n    # ${l}: single pass, O(n)\n    ...`],
    (l) => ["test", `12 / 12 tests passed (${l}, edge cases included)`],
  ],
  transfer: [
    (l) => ["transcript", `"This is the same pattern as ${l}, just over a different structure."`],
    (l) => ["code", `# applied ${l} to a new problem family\nfor window in windows(seq): ...`],
  ],
  retention: [
    (l) => ["transcript", `"Recalled after 6 days: ${l} trades space for time because..."`],
    (l) => ["test", `Spaced review: ${l} recalled correctly, no hints`],
  ],
};

const DIMENSION_CHARACTER: Record<Dimension, Character> = {
  explanation: "drona",
  application: "arjuna",
  transfer: "arjuna",
  retention: "bhima",
};

/** Mock evidence cards for one plant part (the Evidence Inspector's data comes from C11/C14). */
export function mockEvidence(
  snapshot: GardenSnapshot,
  conceptId: string,
  part: PlantPart,
): EvidenceCardData[] {
  const plant = snapshot.plants.find((p) => p.conceptId === conceptId);
  if (!plant) return [];
  const dimension = PART_TO_DIMENSION[part];
  const score = plant.dimensions[dimension];
  if (score.independent === 0 && score.assisted === 0) return [];
  const rng = createRng(`evidence:${conceptId}:${part}`);
  const count = 2 + Math.floor(rng() * 3);
  return Array.from({ length: count }, (_, i) => {
    const template = EXCERPTS[dimension][i % EXCERPTS[dimension].length];
    const [kind, excerpt]: [EvidenceCardData["kind"], string] = template
      ? template(plant.label)
      : ["transcript", ""];
    const independent = i === 0 ? score.independent >= score.assisted : rng() < score.independent;
    return {
      id: `${conceptId}:${part}:${i}`,
      dimension,
      kind,
      character: DIMENSION_CHARACTER[dimension],
      title: `${DIMENSION_TO_PART[dimension]} · ${kind}`,
      excerpt,
      occurredAt: plant.lastEvidenceAt ?? snapshot.createdAt,
      independent,
      uncertainty: Math.round(range(rng, 0.05, 0.35) * 100) / 100,
      rubricVersion: "cs-core@v1/mock",
    };
  });
}
