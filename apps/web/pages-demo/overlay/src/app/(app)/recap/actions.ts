import type { RecapPayload, RecapSegment } from "@sg/audio";
import type { GardenDataset } from "@sg/contracts";

import { DAY_MS, plantsAt } from "@/lib/garden/derive";
import { DEFAULT_STATE } from "@/lib/garden/state";
import { getPracticeDataset } from "@/lib/practice/dataset";

/**
 * Static-site versions of the recap page's Server Actions. Sanjaya's recap is composed in the
 * browser from the week's growth events, citing their evidence; it is narrated by the browser's
 * voice. Private links need the server, so the page does not offer them here.
 */
export type ActionResult<T> = { ok: true; data: T } | { ok: false; message: string };

const MS_PER_CHAR = 64;

/** ISO 8601 week, e.g. `2026-W40`, and its Monday. */
function isoWeek(ms: number): { week: string; monday: number } {
  const date = new Date(ms);
  const day = (date.getUTCDay() + 6) % 7; // Monday = 0
  const monday = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() - day);
  const thursday = new Date(monday + 3 * DAY_MS);
  const year = thursday.getUTCFullYear();
  const firstThursday = new Date(Date.UTC(year, 0, 4));
  const firstMonday = Date.UTC(year, 0, 4) - ((firstThursday.getUTCDay() + 6) % 7) * DAY_MS;
  const week = 1 + Math.round((monday - firstMonday) / (7 * DAY_MS));
  return { week: `${year}-W${String(week).padStart(2, "0")}`, monday };
}

export function buildRecap(dataset: GardenDataset): RecapPayload {
  const now = Date.parse(dataset.generatedAt);
  const since = now - 7 * DAY_MS;
  const title = new Map(dataset.plants.map((p) => [p.key, p.title]));
  const evidence = new Map(dataset.evidence.map((e) => [e.id, e]));
  const recent = dataset.growthEvents.filter((g) => Date.parse(g.occurredAt) >= since);
  const plants = plantsAt(dataset, DEFAULT_STATE.filters, now);
  const wilting = plants.filter((p) => p.wilting);

  // The latest growth per plant, independent first: what the week was about.
  const byPlant = new Map<string, (typeof recent)[number]>();
  for (const g of [...recent].reverse()) if (!byPlant.has(g.plantKey)) byPlant.set(g.plantKey, g);
  const highlights = [...byPlant.values()]
    .sort((a, b) => {
      const ia = evidence.get(a.evidenceIds[0])?.kind === "independent" ? 0 : 1;
      const ib = evidence.get(b.evidenceIds[0])?.kind === "independent" ? 0 : 1;
      return ia - ib || b.occurredAt.localeCompare(a.occurredAt);
    })
    .slice(0, 4);

  const drafts: Omit<RecapSegment, "startMs" | "endMs">[] = [];
  const streak = dataset.streakDays;
  drafts.push({
    id: "intro",
    kind: "intro",
    focus: "garden",
    conceptId: null,
    evidenceIds: [],
    text: recent.length
      ? `Here is your week. ${recent.length} growth ${recent.length === 1 ? "event" : "events"} across ${byPlant.size} ${byPlant.size === 1 ? "plant" : "plants"}, and a ${streak}-day streak.`
      : "A quiet week in the garden. Nothing new grew, but everything you earned before is still here.",
  });
  for (const g of highlights) {
    const e = evidence.get(g.evidenceIds[0]);
    const quote = e?.quote
      ? ` You said: “${e.quote.length > 120 ? `${e.quote.slice(0, 117)}…` : e.quote}”`
      : "";
    drafts.push({
      id: `grew-${g.id}`,
      kind: "growth",
      focus: `plant:${g.plantKey}`,
      conceptId: g.plantKey,
      evidenceIds: [...g.evidenceIds],
      text: `${title.get(g.plantKey) ?? g.plantKey}: ${g.summary.toLowerCase()}.${quote}`,
    });
  }
  if (wilting.length) {
    const names = wilting.slice(0, 3).map((p) => p.meta.title);
    drafts.push({
      id: "reviews",
      kind: "reviews",
      focus: `plant:${wilting[0]!.meta.key}`,
      conceptId: wilting[0]!.meta.key,
      evidenceIds: [],
      text: `${names.join(", ")} ${wilting.length === 1 ? "is" : "are"} starting to wilt. A short review brings ${wilting.length === 1 ? "it" : "them"} back.`,
    });
  }
  const next = dataset.nextBest[0];
  if (next)
    drafts.push({
      id: "next",
      kind: "next",
      focus: `plant:${next.plantKey}`,
      conceptId: next.plantKey,
      evidenceIds: next.evidenceIds,
      text: `Next week: ${next.title}. ${next.reason}`,
    });
  drafts.push({
    id: "outro",
    kind: "outro",
    focus: "garden",
    conceptId: null,
    evidenceIds: [],
    text: "Every leaf here is backed by something you said or ran. See you next week.",
  });

  let at = 0;
  const segments: RecapSegment[] = drafts.map((d) => {
    const duration = Math.max(3500, d.text.length * MS_PER_CHAR + 700);
    const segment = { ...d, startMs: at, endMs: at + duration };
    at += duration;
    return segment;
  });
  const { week, monday } = isoWeek(now);
  const citations = [...new Set(segments.flatMap((s) => s.evidenceIds))];
  return {
    week,
    weekStart: new Date(monday).toISOString().slice(0, 10),
    weekEnd: new Date(monday + 6 * DAY_MS).toISOString().slice(0, 10),
    generatedAt: new Date(now).toISOString(),
    narration: segments.map((s) => s.text).join(" "),
    segments,
    citations,
    durationMs: at,
    timing: "estimated",
    quiet: recent.length === 0,
    rulesVersion: dataset.freshness.rulesVersion,
    audioUrl: null,
    shared: false,
  };
}

export async function generateRecap(_force = false): Promise<ActionResult<RecapPayload>> {
  return { ok: true, data: buildRecap(getPracticeDataset()) };
}

export async function shareRecap(_week: string): Promise<ActionResult<{ path: string }>> {
  return { ok: false, message: "Private links are created by the Skill Garden service." };
}

export async function unshareRecap(_week: string): Promise<ActionResult<null>> {
  return { ok: true, data: null };
}
