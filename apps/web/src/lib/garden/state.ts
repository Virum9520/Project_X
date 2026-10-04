import {
  CHARACTERS,
  DIMENSION_TO_PART,
  type Character,
  type Dimension,
  type EvidenceDimension,
  type FocusTarget,
  type GardenDataset,
  type GardenFilters,
  type GroveId,
} from "@sg/contracts";

/** Everything the URL carries, so any zoomed or filtered view can be linked to. */
export interface DashboardState {
  filters: GardenFilters;
  /** `YYYY-MM-DD` of the time-travel scrubber, or null for "now". */
  scrubDate: string | null;
  focus: FocusTarget;
}

export const DEFAULT_STATE: DashboardState = {
  filters: { evidence: "all" },
  scrubDate: null,
  focus: { level: "garden" },
};

export const DIMENSION_FILTERS: EvidenceDimension[] = [
  "explanation",
  "application",
  "transfer",
  "retention",
  "communication",
];

export const PART_TO_DIMENSION = Object.fromEntries(
  Object.entries(DIMENSION_TO_PART).map(([d, p]) => [p, d]),
) as Record<string, Dimension>;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
export const isIsoDate = (v: string | undefined | null): v is string =>
  !!v && ISO_DATE.test(v) && !Number.isNaN(Date.parse(`${v}T00:00:00Z`));

type Params = Record<string, string | string[] | undefined>;
const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

/** Untrusted input (URL, agent tool args) is validated against the dataset before use. */
export function parseState(params: Params, dataset: GardenDataset): DashboardState {
  const groves = new Set<string>(dataset.groves.map((g) => g.id));
  const plants = new Set(dataset.plants.map((p) => p.key));
  const grove = first(params.grove);
  const dim = first(params.dim);
  const char = first(params.char);
  const from = first(params.from);
  const to = first(params.to);
  const t = first(params.t);

  const filters: GardenFilters = {
    evidence: first(params.ev) === "independent_only" ? "independent_only" : "all",
    grove: grove && groves.has(grove) ? (grove as GroveId) : undefined,
    dimension: DIMENSION_FILTERS.includes(dim as EvidenceDimension)
      ? (dim as EvidenceDimension)
      : undefined,
    character: CHARACTERS.includes(char as Character) ? (char as Character) : undefined,
    dateFrom: isIsoDate(from) ? from : undefined,
    dateTo: isIsoDate(to) ? to : undefined,
  };

  let focus: FocusTarget = { level: "garden" };
  const [level, a, b] = (first(params.focus) ?? "").split(":");
  if (level === "grove" && a && groves.has(a)) focus = { level, groveId: a as GroveId };
  else if (level === "plant" && a && plants.has(a)) focus = { level, plantKey: a };
  else if (level === "part" && a && plants.has(a) && b && b in DIMENSION_TO_PART)
    focus = { level, plantKey: a, part: b as Dimension };

  return { filters, scrubDate: isIsoDate(t) ? t : null, focus };
}

export function serializeState(s: DashboardState): string {
  const q = new URLSearchParams();
  const { filters: f } = s;
  if (f.grove) q.set("grove", f.grove);
  if (f.dimension) q.set("dim", f.dimension);
  if (f.character) q.set("char", f.character);
  if (f.evidence === "independent_only") q.set("ev", "independent_only");
  if (f.dateFrom) q.set("from", f.dateFrom);
  if (f.dateTo) q.set("to", f.dateTo);
  if (s.scrubDate) q.set("t", s.scrubDate);
  const fo = s.focus;
  if (fo.level === "grove") q.set("focus", `grove:${fo.groveId}`);
  if (fo.level === "plant") q.set("focus", `plant:${fo.plantKey}`);
  if (fo.level === "part") q.set("focus", `part:${fo.plantKey}:${fo.part}`);
  return q.toString();
}

/** The grove a focus target lives in (for context-aware rails). */
export function focusGrove(focus: FocusTarget, dataset: GardenDataset): GroveId | null {
  if (focus.level === "grove") return focus.groveId;
  if (focus.level === "plant" || focus.level === "part")
    return dataset.plants.find((p) => p.key === focus.plantKey)?.grove ?? null;
  return null;
}
