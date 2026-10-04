import type { AskSanjayaAnswer, GardenDataset, MemoryItem, PlantState } from "@sg/contracts";

import {
  DAY_MS,
  independentRatio,
  plantsAt,
  readiness,
  reviewStats,
  stageRank,
} from "@/lib/garden/derive";
import { DEFAULT_STATE } from "@/lib/garden/state";
import { getPracticeDataset } from "@/lib/practice/dataset";
import { newId, updateRecords } from "@/lib/practice/store";

/**
 * Static-site versions of the dashboard's Server Actions. They run in the browser: memory
 * corrections are saved with the rest of this browser's practice, and Sanjaya answers from the
 * same numbers the dashboard shows, citing the evidence behind them.
 */
export type ActionResult<T> = { ok: true; data: T } | { ok: false; message: string };

export async function correctMemory(
  id: string,
  content: string,
): Promise<ActionResult<MemoryItem>> {
  const current = getPracticeDataset().memories.find((m) => m.id === id);
  if (!current) return { ok: false, message: "That memory no longer exists." };
  const text = content.replace(/\s+/g, " ").trim().slice(0, 2000);
  if (!text) return { ok: false, message: "Write the corrected memory first." };
  const revised: MemoryItem = {
    ...current,
    id: newId("mem"),
    text,
    why: `Corrected by you on ${new Date().toLocaleDateString("en-US", { month: "short", day: "numeric" })}. Was: “${current.text}”`,
    status: "accepted",
    confidence: Math.max(current.confidence, 0.95),
  };
  const saved = updateRecords((r) => ({ ...r, memoryEdits: { ...r.memoryEdits, [id]: revised } }));
  return saved
    ? { ok: true, data: revised }
    : { ok: false, message: "This browser did not let the correction be saved." };
}

export async function deleteMemory(id: string): Promise<ActionResult<null>> {
  const current = getPracticeDataset().memories.find((m) => m.id === id);
  if (!current) return { ok: true, data: null };
  if (!current.deletable)
    return {
      ok: false,
      message: "Only private reflections can be deleted. Correct this one instead.",
    };
  updateRecords((r) => ({ ...r, deletedMemories: [...r.deletedMemories, id] }));
  return { ok: true, data: null };
}

// ─── Ask Sanjaya ─────────────────────────────────────────────────────────────────────────────

const pct = (x: number) => `${Math.round(x)}%`;

interface Garden {
  dataset: GardenDataset;
  plants: PlantState[];
  cutoff: number;
  title: (key: string) => string;
  latestEvidence: (key: string, kind?: "independent" | "assisted") => string | undefined;
}

function garden(): Garden {
  const dataset = getPracticeDataset();
  const cutoff = Date.parse(dataset.generatedAt);
  const plants = plantsAt(dataset, DEFAULT_STATE.filters, cutoff);
  const titles = new Map(dataset.plants.map((p) => [p.key, p.title]));
  return {
    dataset,
    plants,
    cutoff,
    title: (key) => titles.get(key) ?? key,
    latestEvidence: (key, kind) =>
      dataset.evidence.findLast((e) => e.plantKey === key && (!kind || e.kind === kind))?.id,
  };
}

const defined = (ids: (string | undefined)[]) => ids.filter((id): id is string => !!id);

function readinessAnswer(g: Garden): AskSanjayaAnswer {
  const r = readiness(g.dataset, g.plants);
  const ranked = [...r.byGrove].sort((a, b) => b.score - a.score);
  const titleOf = new Map(g.dataset.groves.map((x) => [x.id, x.title]));
  const best = ranked[0];
  const worst = ranked[ranked.length - 1];
  const ratio = independentRatio(g.plants);
  const strongest = [...g.plants].sort((a, b) => stageRank(b.stage) - stageRank(a.stage))[0];
  const answer = [
    `You are at ${pct(r.overall)} readiness for ${g.dataset.readiness.targetRole}, counting only what you showed on your own.`,
    best && worst
      ? `${titleOf.get(best.grove)} is your strongest grove (${pct(best.score)}); ${titleOf.get(worst.grove)} needs the most work (${pct(worst.score)}).`
      : "",
    ratio.share !== null
      ? `${pct(ratio.share * 100)} of your evidence is independent, which is what counts in an interview.`
      : "",
  ]
    .filter(Boolean)
    .join(" ");
  return {
    answer,
    citations: defined([
      strongest && g.latestEvidence(strongest.meta.key, "independent"),
      g.dataset.nextBest[0]?.evidenceIds[0],
    ]),
    metrics: [`readiness ${pct(r.overall)}`, `independent share ${pct((ratio.share ?? 0) * 100)}`],
    grounded: true,
  };
}

function focusAnswer(g: Garden): AskSanjayaAnswer {
  const next = g.dataset.nextBest[0];
  const reviews = reviewStats(g.plants, g.cutoff);
  const wilting = g.plants.filter((p) => p.wilting).slice(0, 2);
  const parts = [
    next
      ? `Next: ${next.title} with ${next.character.charAt(0).toUpperCase()}${next.character.slice(1)}, about ${next.minutes} minutes. ${next.reason}`
      : "Pick any sprouting plant and explain it out loud to Drona.",
    wilting.length
      ? `Also, ${wilting.map((p) => g.title(p.meta.key)).join(" and ")} ${wilting.length > 1 ? "are" : "is"} overdue for review, so a short check-in keeps ${wilting.length > 1 ? "them" : "it"} from wilting.`
      : "",
  ];
  return {
    answer: parts.filter(Boolean).join(" "),
    citations: defined([
      ...(next?.evidenceIds ?? []),
      ...wilting.map((p) => g.latestEvidence(p.meta.key)),
    ]),
    metrics: [`overdue reviews ${reviews.overdue}`, `due soon ${reviews.dueSoon}`],
    grounded: true,
  };
}

function weekAnswer(g: Garden): AskSanjayaAnswer {
  const since = g.cutoff - 7 * DAY_MS;
  const recent = g.dataset.growthEvents.filter((e) => Date.parse(e.occurredAt) >= since);
  if (!recent.length)
    return {
      answer: "Nothing grew in the last seven days. One short session is enough to start again.",
      citations: [],
      metrics: ["growth events this week 0"],
      grounded: true,
    };
  const latest = [...recent].reverse();
  const plants = [...new Set(latest.map((e) => e.plantKey))];
  const examples = latest
    .slice(0, 3)
    .map((e) => `${g.title(e.plantKey)}: ${e.summary.toLowerCase()}`);
  return {
    answer: `This week ${recent.length} growth ${recent.length === 1 ? "event" : "events"} touched ${plants.length} ${plants.length === 1 ? "plant" : "plants"}. Most recent: ${examples.join("; ")}. Each one cites what you said or ran.`,
    citations: latest.slice(0, 4).map((e) => e.evidenceIds[0]),
    metrics: [`growth events this week ${recent.length}`, `plants touched ${plants.length}`],
    grounded: true,
  };
}

function reviewAnswer(g: Garden): AskSanjayaAnswer {
  const overdue = g.plants
    .filter((p) => p.wilting)
    .sort((a, b) => Date.parse(a.nextReviewAt ?? "") - Date.parse(b.nextReviewAt ?? ""));
  if (!overdue.length)
    return {
      answer: "No reviews are overdue. Your next ones come due over the coming days.",
      citations: [],
      metrics: ["overdue reviews 0"],
      grounded: true,
    };
  const names = overdue.slice(0, 4).map((p) => g.title(p.meta.key));
  return {
    answer: `${overdue.length} ${overdue.length === 1 ? "plant is" : "plants are"} overdue: ${names.join(", ")}${overdue.length > 4 ? " and more" : ""}. A quick retention check with Bhima, or a two-minute explanation to Drona, brings ${overdue.length === 1 ? "it" : "them"} back.`,
    citations: defined(overdue.slice(0, 4).map((p) => g.latestEvidence(p.meta.key))),
    metrics: [`overdue reviews ${overdue.length}`],
    grounded: true,
  };
}

function plantAnswer(g: Garden, plant: PlantState): AskSanjayaAnswer {
  const title = plant.meta.title;
  const dims = (["explanation", "application", "transfer", "retention"] as const)
    .map((d) => ({ d, ind: plant.independent[d] ?? 0, asst: plant.assisted[d] ?? 0 }))
    .filter((x) => x.ind > 0 || x.asst > 0);
  const assistedOnly = dims.filter((x) => x.asst > 0 && x.ind < 0.5).map((x) => x.d);
  let answer = `${title} is ${plant.stage === "unassessed" ? "not assessed yet" : `at the ${plant.stage} stage`}.`;
  if (plant.stage === "assisted" || assistedOnly.length)
    answer += ` Its ${assistedOnly.join(" and ") || "evidence"} came with hints, and assisted evidence never counts as independent. Show it once on your own and it will grow.`;
  else if (plant.stage === "unassessed")
    answer += " Explain it to Drona or solve a problem with Arjuna to plant it.";
  else
    answer += ` Strongest: ${dims.sort((a, b) => b.ind - a.ind)[0]?.d ?? "explanation"}. ${plant.wilting ? "It is overdue for review." : plant.nextReviewAt ? `Next review ${new Date(plant.nextReviewAt).toLocaleDateString("en-US", { month: "short", day: "numeric" })}.` : ""}`;
  return {
    answer: answer.trim(),
    citations: defined([
      g.latestEvidence(plant.meta.key, "independent"),
      g.latestEvidence(plant.meta.key, "assisted"),
    ]),
    metrics: [`${title} stage ${plant.stage}`],
    grounded: true,
  };
}

function findPlant(g: Garden, question: string): PlantState | undefined {
  const q = question.toLowerCase();
  return [...g.plants]
    .sort((a, b) => b.meta.title.length - a.meta.title.length)
    .find((p) => {
      const words = p.meta.title.toLowerCase().split(/[,(]/)[0]!.trim();
      return q.includes(words) || q.includes(p.meta.key.split(".")[1]!.replaceAll("_", " "));
    });
}

export async function askSanjaya(question: string): Promise<ActionResult<AskSanjayaAnswer>> {
  const q = question.trim().slice(0, 500);
  if (!q) return { ok: false, message: "Ask a question about your garden." };
  const g = garden();
  const lower = q.toLowerCase();
  const plant = findPlant(g, lower);
  if (plant) return { ok: true, data: plantAnswer(g, plant) };
  if (/overdue|review|due|wilt|forget/.test(lower)) return { ok: true, data: reviewAnswer(g) };
  if (/change|week|grew|grow|progress|recent|lately/.test(lower))
    return { ok: true, data: weekAnswer(g) };
  if (/focus|next|should|practi[cs]e|improve|work on|weak/.test(lower))
    return { ok: true, data: focusAnswer(g) };
  if (/ready|readiness|interview|job|score|strong/.test(lower))
    return { ok: true, data: readinessAnswer(g) };
  const r = readiness(g.dataset, g.plants);
  const growing = g.plants.filter((p) => p.stage !== "unassessed").length;
  return {
    ok: true,
    data: {
      answer: `Your garden has ${growing} of ${g.plants.length} plants growing, ${pct(r.overall)} readiness and a ${g.dataset.streakDays}-day streak. Ask me about a topic by name, what to practise next, what changed this week, or which reviews are overdue.`,
      citations: [],
      metrics: [`plants growing ${growing}`, `readiness ${pct(r.overall)}`],
      grounded: true,
    },
  };
}
