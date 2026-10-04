import type {
  EvidenceItem,
  GrowthEvent,
  MemoryItem,
  Misconception,
  SessionMarker,
} from "@sg/contracts";

import type { Schedule } from "@/lib/accountability/types";

/**
 * What practice in this browser has produced, kept in `localStorage`: the evidence, growth events
 * and sessions it added to the garden, memory corrections, Bhima's schedule and the interview
 * plan. Nothing leaves the browser. Reads never throw (private mode or a full quota just means
 * nothing is remembered), and every change notifies subscribers in this tab and in other tabs.
 */
export interface SavedPlan {
  role: string;
  resume: string;
  jobDescription: string;
  savedAt: string;
}

export interface PracticeRecords {
  evidence: EvidenceItem[];
  growthEvents: GrowthEvent[];
  sessions: SessionMarker[];
  /** New memories from practice (for example a commitment told to Bhima). */
  memories: MemoryItem[];
  /** Corrections to existing memories, keyed by the id the memory had when it was corrected. */
  memoryEdits: Record<string, MemoryItem>;
  deletedMemories: string[];
  misconceptions: Misconception[];
  schedules: Schedule[];
  plan: SavedPlan | null;
}

const KEY = "sg.practice.v1";

const empty = (): PracticeRecords => ({
  evidence: [],
  growthEvents: [],
  sessions: [],
  memories: [],
  memoryEdits: {},
  deletedMemories: [],
  misconceptions: [],
  schedules: [],
  plan: null,
});

let cache: { raw: string | null; records: PracticeRecords } | null = null;
let version = 0;
const listeners = new Set<() => void>();

function rawValue(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function readRecords(): PracticeRecords {
  if (typeof window === "undefined") return empty();
  const raw = rawValue();
  if (cache && cache.raw === raw) return cache.records;
  let records = empty();
  if (raw) {
    try {
      records = { ...records, ...(JSON.parse(raw) as Partial<PracticeRecords>) };
    } catch {
      // A corrupt value is ignored rather than breaking every page.
    }
  }
  cache = { raw, records };
  return records;
}

function notify() {
  version += 1;
  for (const listener of listeners) listener();
}

/** Apply a change and save it. Returns false when the browser refused to store it. */
export function updateRecords(change: (records: PracticeRecords) => PracticeRecords): boolean {
  const next = change(readRecords());
  const raw = JSON.stringify(next);
  let saved = true;
  try {
    window.localStorage.setItem(KEY, raw);
  } catch {
    saved = false;
  }
  cache = { raw: saved ? raw : rawValue(), records: next };
  notify();
  return saved;
}

let watchingOtherTabs = false;

export function subscribeRecords(listener: () => void): () => void {
  if (!watchingOtherTabs) {
    watchingOtherTabs = true;
    // Another tab saved practice: `readRecords` sees the new value, subscribers re-read.
    window.addEventListener("storage", (event) => {
      if (event.key === KEY || event.key === null) notify();
    });
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Changes with every write in this tab or another one; cheap to compare in snapshots. */
export const recordsVersion = () => version;

export function clearRecords() {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // Nothing stored, nothing to clear.
  }
  cache = null;
  notify();
}

/** A short random id for records created in the browser. */
export const newId = (prefix: string) =>
  `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
