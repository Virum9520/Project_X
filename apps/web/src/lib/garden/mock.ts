/**
 * Deterministic mock learner for the Garden Dashboard. Concept keys and titles come from the real
 * `cs-core@v1` curriculum. Everything here is MOCK DATA: it is replaced by the analytics API
 * (C09/C10) behind `./data.ts`. The only other importer is the static GitHub Pages build
 * (`pages-demo/overlay/src/lib/practice/dataset.ts`), which has no API.
 */
import {
  DIMENSION_TO_PART,
  type Character,
  type EvidenceDimension,
  type EvidenceItem,
  type GardenDataset,
  type GrowthEvent,
  type GroveId,
  type MemoryItem,
  type Misconception,
  type PlantMeta,
  type PlantStage,
  type SessionMarker,
} from "@sg/contracts";

import { DAY_MS, stageOf } from "./derive";

const GROVES: { id: GroveId; title: string }[] = [
  { id: "dsa", title: "Data structures & algorithms" },
  { id: "os", title: "Operating systems" },
  { id: "networks", title: "Computer networks" },
  { id: "databases", title: "Databases" },
  { id: "system_design", title: "System design" },
  { id: "behavioral", title: "Behavioral" },
];

/** key, title, difficulty, gist (what the learner "said"), script. See `parseScript`. */
type PlantSpec = [string, string, 1 | 2 | 3 | 4 | 5, string, string];

/**
 * Script: `daysAgo:dimension:kind:character:strength`, comma separated.
 * dimension e=explanation a=application t=transfer r=retention c=communication
 * kind i=independent a=assisted; character d=drona r=arjuna v=vidura. Strength is the judge score.
 */
const SPECS: PlantSpec[] = [
  [
    "dsa.big_o",
    "Big-O, time and space complexity",
    1,
    "growth rate as the input size grows",
    "38:e:i:d:.9,36:a:i:r:.8,20:t:i:d:.8,6:r:i:d:.8",
  ],
  ["dsa.arrays", "Arrays", 1, "contiguous memory gives O(1) indexing", "35:e:i:d:.9,34:a:i:r:.8"],
  [
    "dsa.stacks",
    "Stacks",
    1,
    "last in, first out, like undo",
    "33:e:i:d:.9,32:a:i:r:.8,12:t:i:d:.8",
  ],
  [
    "dsa.hash_tables",
    "Hash tables",
    2,
    "a hash function maps keys to buckets",
    "30:e:i:d:.9,29:a:i:r:.9,14:t:i:d:.8,3:r:i:d:.8",
  ],
  [
    "dsa.sorting",
    "Sorting",
    2,
    "merge sort splits then merges in O(n log n)",
    "22:e:i:d:.9,21:a:i:r:.8",
  ],
  [
    "dsa.two_pointers",
    "Two pointers",
    2,
    "move two indexes inward on a sorted array",
    "24:e:a:d:.8,23:a:a:r:.7",
  ],
  [
    "dsa.sliding_window",
    "Sliding window",
    2,
    "keep a window and update it as it slides",
    "10:e:a:d:.7,9:a:a:r:.7,2:e:i:d:.9",
  ],
  [
    "dsa.binary_search",
    "Binary search",
    2,
    "halve the search range each step",
    "18:e:i:d:.9,17:a:i:r:.9,4:t:i:d:.8",
  ],
  [
    "dsa.recursion",
    "Recursion",
    2,
    "a base case plus a smaller subproblem",
    "16:e:i:d:.9,15:a:a:r:.7",
  ],
  [
    "dsa.binary_trees",
    "Binary trees",
    3,
    "each node has at most two children",
    "12:e:i:d:.9,11:a:i:r:.8",
  ],
  [
    "dsa.graph_representation",
    "Graph representation",
    3,
    "adjacency list versus matrix trade-offs",
    "8:e:i:d:.9,7:a:i:r:.8",
  ],
  [
    "dsa.bfs",
    "Breadth-first search",
    3,
    "explore level by level with a queue",
    "9:e:i:d:.9,8:a:i:r:.9,1:t:a:r:.8",
  ],
  [
    "dsa.dfs",
    "Depth-first search",
    3,
    "go deep first, using the call stack or a stack",
    "7:e:a:d:.8,6:a:a:r:.7",
  ],
  [
    "dsa.dynamic_programming",
    "Dynamic programming",
    4,
    "cache overlapping subproblems",
    "5:e:a:d:.7,3:a:a:r:.6",
  ],
  ["dsa.heaps", "Heaps", 3, "", ""],
  ["dsa.tries", "Tries", 3, "", ""],
  ["dsa.union_find", "Union-find", 3, "", ""],
  [
    "os.processes_threads",
    "Processes and threads",
    2,
    "threads share an address space, processes do not",
    "27:e:i:d:.9,26:a:i:r:.8,10:t:i:d:.8",
  ],
  [
    "os.memory_layout",
    "Process memory layout",
    2,
    "stack, heap, data and text segments",
    "19:e:i:d:.9,18:a:a:r:.7",
  ],
  [
    "os.race_conditions",
    "Race conditions",
    3,
    "outcome depends on thread timing",
    "12:e:a:d:.8,5:e:i:d:.9",
  ],
  [
    "os.synchronization",
    "Synchronization",
    3,
    "locks make a critical section atomic",
    "4:e:a:d:.7",
  ],
  [
    "os.deadlocks",
    "Deadlocks",
    3,
    "four conditions, break any one to prevent it",
    "3:e:i:d:.9,3:a:i:r:.8",
  ],
  ["os.cpu_scheduling", "CPU scheduling", 2, "", ""],
  ["os.virtual_memory", "Virtual memory", 3, "", ""],
  [
    "networks.tcp",
    "TCP",
    2,
    "a three-way handshake sets up a reliable stream",
    "23:e:i:d:.9,22:a:i:r:.8,8:t:i:d:.8",
  ],
  ["networks.http", "HTTP", 1, "stateless request and response", "21:e:i:d:.9,20:a:i:r:.8"],
  ["networks.dns", "DNS", 2, "resolvers walk from root to authoritative servers", "13:e:a:d:.7"],
  ["networks.tls", "TLS", 3, "", ""],
  [
    "databases.joins_aggregation",
    "Joins and aggregation",
    2,
    "inner join keeps only matching rows",
    "31:e:i:d:.9,30:a:i:r:.9,9:t:i:d:.8,1:r:i:d:.8",
  ],
  [
    "databases.indexes",
    "Indexes",
    3,
    "a B-tree trades write cost for read speed",
    "15:e:i:d:.9,14:a:i:r:.8,2:t:a:d:.7",
  ],
  [
    "databases.transactions_acid",
    "Transactions and ACID",
    3,
    "all or nothing, and isolated from others",
    "11:e:i:d:.9,10:a:a:r:.7",
  ],
  [
    "databases.isolation_levels",
    "Isolation levels",
    4,
    "read committed still allows non-repeatable reads",
    "6:e:a:d:.6",
  ],
  [
    "system_design.caching",
    "Caching",
    3,
    "cache-aside with a TTL to bound staleness",
    "5:e:a:d:.7",
  ],
  [
    "system_design.load_balancing",
    "Load balancing",
    3,
    "spread requests across healthy servers",
    "2:e:i:d:.9",
  ],
  ["system_design.rate_limiting", "Rate limiting", 3, "", ""],
  ["system_design.cap_consistency", "CAP and consistency", 4, "", ""],
  [
    "behavioral.star_method",
    "STAR method",
    1,
    "situation, task, action, result",
    "26:e:i:v:.9,25:a:i:v:.8,7:t:i:v:.8",
  ],
  [
    "behavioral.conflict_resolution",
    "Conflict resolution",
    2,
    "listened first, then proposed a trade-off",
    "8:e:a:v:.7,8:c:i:v:.8",
  ],
  [
    "behavioral.ownership",
    "Ownership",
    2,
    "took the bug through to the postmortem",
    "3:e:i:v:.9,3:c:i:v:.8",
  ],
  ["behavioral.failure_learning", "Learning from failure", 2, "", ""],
];

const CHAR: Record<string, Character> = { d: "drona", r: "arjuna", v: "vidura" };
const DIM: Record<string, EvidenceDimension> = {
  e: "explanation",
  a: "application",
  t: "transfer",
  r: "retention",
  c: "communication",
};

const RATIONALE: Record<EvidenceDimension, string> = {
  explanation: "States the idea in their own words and covers the rubric's core criteria.",
  application: "Applies the idea correctly to a concrete problem; the approach and result hold.",
  transfer: "Uses the idea in a new setting without being shown how it carries over.",
  retention: "Recalls and uses the idea unprompted after a gap of days.",
  communication: "Structured, specific and concise; the point lands in the first sentence.",
};

function quoteFor(dim: EvidenceDimension, title: string, gist: string, kind: "i" | "a") {
  const lead = kind === "a" ? "Okay, so if I follow your hint, " : "";
  switch (dim) {
    case "explanation":
      return `${lead}${title} is basically ${gist}.`;
    case "application":
      return `${lead}I'd use it here because ${gist}, so the loop only needs one pass.`;
    case "transfer":
      return `This isn't the same problem, but ${gist} still holds, so I'd reuse it for the new input.`;
    case "retention":
      return `Last week we covered this: ${gist}. I'd start there before reaching for anything fancier.`;
    default:
      return `In that project I ${gist}, and the result was a fix that shipped that week.`;
  }
}

function anchor(now: Date) {
  const midnight = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return midnight;
}

export function buildMockDataset(now: Date = new Date()): GardenDataset {
  const dayZero = anchor(now);
  const plants: PlantMeta[] = SPECS.map(([key, title, difficulty]) => ({
    key,
    title,
    grove: key.split(".")[0] as GroveId,
    difficulty,
  }));
  const titleOf = new Map(SPECS.map((s) => [s[0], s[1]]));

  // Evidence ───────────────────────────────────────────────────────────────────────────────
  const evidence: EvidenceItem[] = [];
  for (const [key, title, , gist, script] of SPECS) {
    if (!script) continue;
    script.split(",").forEach((step, n) => {
      const [daysAgo, d, k, c, s] = step.split(":");
      const dimension = DIM[d]!;
      const kind = k === "i" ? ("independent" as const) : ("assisted" as const);
      const t = dayZero - Number(daysAgo) * DAY_MS + (9 + (n % 5) * 2) * 3_600_000;
      const character = CHAR[c]!;
      evidence.push({
        id: `ev_${key.replace(".", "_")}_${n + 1}`,
        plantKey: key,
        dimension,
        kind,
        character,
        sessionId: `ses_${daysAgo}_${character}`,
        occurredAt: new Date(t).toISOString(),
        quote: quoteFor(dimension, title, gist, k as "i" | "a"),
        source: character === "arjuna" && dimension === "application" ? "code" : "transcript",
        rationale: RATIONALE[dimension],
        assistNote:
          kind === "assisted"
            ? "Learner needed two hints and a leading question before answering."
            : undefined,
        confidence: 0.85 + (n % 3) * 0.05,
        weight: Number(s),
        rubricVersion: "cs-core@v1/rubric.1",
        status: key === "os.synchronization" ? "provisional" : "confirmed",
      });
    });
  }
  evidence.sort((a, b) => a.occurredAt.localeCompare(b.occurredAt));

  // Growth events: replay evidence in order; every event cites the evidence that caused it. ──
  const state = new Map<string, { ind: Record<string, number>; any: boolean; hasInd: boolean }>();
  const stageNow = new Map<string, PlantStage>();
  const growthEvents: GrowthEvent[] = [];
  evidence.forEach((e, i) => {
    const s = state.get(e.plantKey) ?? { ind: {}, any: false, hasInd: false };
    const before = stageNow.get(e.plantKey) ?? "unassessed";
    s.any = true;
    if (e.kind === "independent") {
      s.hasInd = true;
      if (e.dimension !== "communication") {
        s.ind[e.dimension] = Math.min(1, (s.ind[e.dimension] ?? 0) + e.weight * e.confidence);
      }
    }
    state.set(e.plantKey, s);
    const after = stageOf(
      {
        explanation: s.ind.explanation ?? null,
        application: s.ind.application ?? null,
        transfer: s.ind.transfer ?? null,
        retention: s.ind.retention ?? null,
      },
      s.any,
      s.hasInd,
    );
    stageNow.set(e.plantKey, after);
    const part = e.dimension === "communication" ? null : DIMENSION_TO_PART[e.dimension];
    const what = part ? `${cap(part)} grew` : "Communication noted";
    growthEvents.push({
      id: `gr_${i + 1}`,
      plantKey: e.plantKey,
      occurredAt: e.occurredAt,
      dimension: e.dimension,
      fromStage: before,
      toStage: after,
      summary: `${what}${e.kind === "assisted" ? " (assisted, with hints)" : ""}`,
      evidenceIds: [e.id],
      revision: i + 1,
    });
  });

  // Sessions: one per (day, character), plus short check-ins so the streak is real. ───────────
  const sessionMap = new Map<string, SessionMarker>();
  for (const e of evidence) {
    const sess = sessionMap.get(e.sessionId);
    if (sess) sess.evidenceIds.push(e.id);
    else
      sessionMap.set(e.sessionId, {
        id: e.sessionId,
        character: e.character,
        startedAt: e.occurredAt,
        minutes: 14 + (e.sessionId.length % 9) * 2,
        title: `${cap(e.character)}: ${titleOf.get(e.plantKey)}`,
        evidenceIds: [e.id],
      });
  }
  for (const d of [1, 2, 3, 4, 5]) {
    const id = `ses_${d}_bhima`;
    sessionMap.set(id, {
      id,
      character: "bhima",
      startedAt: new Date(dayZero - d * DAY_MS + 20 * 3_600_000).toISOString(),
      minutes: 6,
      title: "Bhima: daily check-in",
      evidenceIds: [],
    });
  }
  const sessions = [...sessionMap.values()].sort((a, b) => a.startedAt.localeCompare(b.startedAt));
  const days = new Set(
    sessions.map((s) => Math.floor((Date.parse(s.startedAt) - dayZero) / DAY_MS)),
  );
  let streakDays = 0;
  for (let d = -1; days.has(d); d--) streakDays += 1;

  const firstEv = (key: string) => evidence.find((e) => e.plantKey === key)!.id;
  const lastEv = (key: string) => evidence.findLast((e) => e.plantKey === key)!.id;

  const memories: MemoryItem[] = [
    mem(
      "m1",
      "drona",
      "profile",
      "Learns fastest from a worked example before the formal definition.",
      "Stated in onboarding and confirmed by three sessions where examples came first.",
      "accepted",
      0.9,
      [firstEv("dsa.big_o")],
      ["dsa.big_o", "dsa.hash_tables"],
      false,
      30,
    ),
    mem(
      "m2",
      "drona",
      "knowledge",
      "Confuses O(2n) with a different class from O(n).",
      "Said so in the Big-O session; corrected by the judge's rubric note.",
      "accepted",
      0.8,
      [firstEv("dsa.big_o")],
      ["dsa.big_o"],
      false,
      38,
    ),
    mem(
      "m3",
      "arjuna",
      "skills",
      "Reaches for brute force first, then optimises when prompted.",
      "Observed across the last four coding rounds.",
      "accepted",
      0.75,
      [firstEv("dsa.binary_search"), firstEv("dsa.bfs")],
      ["dsa.binary_search", "dsa.bfs", "dsa.dynamic_programming"],
      false,
      8,
    ),
    mem(
      "m4",
      "arjuna",
      "knowledge",
      "Needs hints to define the subproblem in dynamic programming.",
      "Two hints were needed in the latest session, so the evidence is assisted.",
      "provisional",
      0.6,
      [lastEv("dsa.dynamic_programming")],
      ["dsa.dynamic_programming"],
      false,
      3,
    ),
    mem(
      "m5",
      "vidura",
      "skills",
      "Opens STAR answers with the result, which lands well.",
      "Judge note from the STAR session.",
      "accepted",
      0.85,
      [firstEv("behavioral.star_method")],
      ["behavioral.star_method"],
      false,
      26,
    ),
    mem(
      "m6",
      "vidura",
      "private",
      "Feels anxious about conflict questions; wants a slower pace.",
      "Shared in a reflection. Private: only you can see it.",
      "accepted",
      0.7,
      [firstEv("behavioral.conflict_resolution")],
      ["behavioral.conflict_resolution"],
      true,
      8,
    ),
    mem(
      "m7",
      "drona",
      "session",
      "Last session ended mid-way through isolation levels.",
      "Interrupted call; resume there next time.",
      "accepted",
      0.9,
      [firstEv("databases.isolation_levels")],
      ["databases.isolation_levels"],
      false,
      6,
    ),
    mem(
      "m8",
      "bhima",
      "commitments",
      "Committed to two 20-minute sessions this week.",
      "Logged during the Sunday check-in.",
      "accepted",
      0.95,
      [],
      [],
      false,
      4,
    ),
    mem(
      "m9",
      "drona",
      "knowledge",
      "Mixes up race conditions and deadlocks.",
      "Disputed by you: you say you only did it once.",
      "disputed",
      0.4,
      [firstEv("os.race_conditions")],
      ["os.race_conditions", "os.deadlocks"],
      false,
      12,
    ),
  ];
  function mem(
    id: string,
    character: Character,
    layer: MemoryItem["layer"],
    text: string,
    why: string,
    status: MemoryItem["status"],
    confidence: number,
    evidenceIds: string[],
    affects: string[],
    deletable: boolean,
    daysAgo: number,
  ): MemoryItem {
    return {
      id,
      character,
      layer,
      text,
      why,
      status,
      confidence,
      evidenceIds,
      affects,
      deletable,
      createdAt: new Date(dayZero - daysAgo * DAY_MS + 10 * 3_600_000).toISOString(),
    };
  }

  const misconceptions: Misconception[] = [
    mk(
      "mc1",
      "dsa.dynamic_programming",
      "Memoization and tabulation have different time complexity.",
      2,
      3,
    ),
    mk("mc2", "dsa.big_o", "O(2n) is a different complexity class from O(n).", 3, 36),
    mk("mc3", "os.race_conditions", "Race conditions only happen on multi-core machines.", 2, 5),
    mk("mc4", "dsa.recursion", "Recursion always uses O(1) extra space.", 1, 15),
  ];
  function mk(
    id: string,
    plantKey: string,
    text: string,
    occurrences: number,
    daysAgo: number,
  ): Misconception {
    return {
      id,
      plantKey,
      text,
      occurrences,
      lastSeenAt: new Date(dayZero - daysAgo * DAY_MS + 12 * 3_600_000).toISOString(),
      evidenceIds: [lastEv(plantKey)],
    };
  }

  return {
    generatedAt: now.toISOString(),
    freshness: {
      projectionAt: now.toISOString(),
      rulesVersion: "profile.demo@mock",
      curriculum: "cs-core@v1",
    },
    readiness: {
      version: "readiness@mock-1",
      targetRole: "New-grad software engineer",
      dimensionWeights: { explanation: 0.3, application: 0.35, transfer: 0.2, retention: 0.15 },
    },
    groves: GROVES,
    plants,
    evidence,
    growthEvents,
    sessions,
    memories,
    misconceptions,
    nextBest: [
      {
        character: "arjuna",
        plantKey: "dsa.dynamic_programming",
        title: "Solve one DP problem without hints",
        reason:
          "Both dynamic programming sessions were assisted, so this plant has no independent evidence yet.",
        minutes: 25,
        evidenceIds: [firstEv("dsa.dynamic_programming"), lastEv("dsa.dynamic_programming")],
      },
      {
        character: "drona",
        plantKey: "dsa.arrays",
        title: "Quick recall check on arrays",
        reason: "Last independent evidence was over a month ago, so the plant is wilting.",
        minutes: 8,
        evidenceIds: [lastEv("dsa.arrays")],
      },
    ],
    streakDays,
  };
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
