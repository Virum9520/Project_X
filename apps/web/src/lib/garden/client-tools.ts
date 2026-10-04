/**
 * Pure handlers for the Sanjaya client tools declared in `agents/tools/{focus_plant,set_filter,
 * scrub_timeline}.yaml`. Arguments come from an LLM, so they are validated against the dataset and
 * answered with a plain-language result (success or a correctable error) the agent can speak.
 *
 * Wire-up: `useGardenDashboard().clientTools` returns these bound to dashboard state, shaped for
 * ElevenLabs' `useConversation({ clientTools })`.
 */
import {
  type FocusPlantArgs,
  type FocusTarget,
  type GardenDataset,
  type GardenFilters,
  type ScrubTimelineArgs,
  type SetFilterArgs,
  ZOOM_LEVELS,
} from "@sg/contracts";

import { DIMENSION_FILTERS, PART_TO_DIMENSION, isIsoDate } from "./state";

export type ToolResult<T> =
  { ok: true; value: T; message: string } | { ok: false; message: string };

const fail = (message: string) => ({ ok: false as const, message });

export function resolveFocusPlant(
  dataset: GardenDataset,
  args: Partial<FocusPlantArgs>,
): ToolResult<FocusTarget> {
  const { level, target_id: id, part } = args;
  if (!level || !ZOOM_LEVELS.includes(level))
    return fail(`level must be one of ${ZOOM_LEVELS.join(", ")}.`);
  if (level === "garden")
    return { ok: true, value: { level }, message: "Showing the whole garden." };

  if (level === "grove") {
    const grove = dataset.groves.find((g) => g.id === id);
    if (!grove)
      return fail(
        `Unknown grove "${id}". Valid groves: ${dataset.groves.map((g) => g.id).join(", ")}.`,
      );
    return {
      ok: true,
      value: { level, groveId: grove.id },
      message: `Focused the ${grove.title} grove.`,
    };
  }

  const plant = dataset.plants.find((p) => p.key === id);
  if (!plant) return fail(`Unknown concept "${id}". Use a concept key such as dsa.bfs.`);
  if (level === "plant")
    return { ok: true, value: { level, plantKey: plant.key }, message: `Focused ${plant.title}.` };

  const dimension = part ? PART_TO_DIMENSION[part] : undefined;
  if (!dimension) return fail("part must be one of roots, stem, branches, blossoms.");
  return {
    ok: true,
    value: { level, plantKey: plant.key, part: dimension },
    message: `Focused the ${part} of ${plant.title}.`,
  };
}

export function resolveSetFilter(
  dataset: GardenDataset,
  args: SetFilterArgs,
): ToolResult<GardenFilters> {
  // Calling with no arguments clears every filter.
  const filters: GardenFilters = { evidence: "all" };
  const notes: string[] = [];

  if (args.domain !== undefined) {
    const grove = dataset.groves.find((g) => g.id === args.domain);
    if (!grove)
      return fail(
        `Unknown domain "${args.domain}". Valid: ${dataset.groves.map((g) => g.id).join(", ")}.`,
      );
    filters.grove = grove.id;
    notes.push(grove.title);
  }
  if (args.dimension !== undefined) {
    if (!DIMENSION_FILTERS.includes(args.dimension))
      return fail(`Unknown dimension "${args.dimension}". Valid: ${DIMENSION_FILTERS.join(", ")}.`);
    filters.dimension = args.dimension;
    notes.push(args.dimension);
  }
  if (args.evidence !== undefined) {
    if (args.evidence !== "all" && args.evidence !== "independent_only")
      return fail('evidence must be "independent_only" or "all".');
    filters.evidence = args.evidence;
    if (args.evidence === "independent_only") notes.push("independent evidence only");
  }
  for (const [key, field] of [
    ["date_from", "dateFrom"],
    ["date_to", "dateTo"],
  ] as const) {
    const v = args[key];
    if (v === undefined) continue;
    if (!isIsoDate(v)) return fail(`${key} must be an ISO date like 2026-09-30.`);
    filters[field] = v;
    notes.push(`${key.replace("_", " ")} ${v}`);
  }
  return {
    ok: true,
    value: filters,
    message: notes.length ? `Filtered to ${notes.join(", ")}.` : "Cleared all filters.",
  };
}

/** `now` returns to the present (null). Dates in the future are rejected. */
export function resolveScrub(
  dataset: GardenDataset,
  args: Partial<ScrubTimelineArgs>,
): ToolResult<string | null> {
  if (args.date === "now") return { ok: true, value: null, message: "Back to the present." };
  if (!isIsoDate(args.date)) return fail('date must be YYYY-MM-DD or "now".');
  const day = Date.parse(`${args.date}T00:00:00Z`);
  if (day > Date.parse(dataset.generatedAt)) return fail("That date is in the future.");
  return {
    ok: true,
    value: args.date,
    message: `Showing the garden as it looked on ${args.date}.`,
  };
}
