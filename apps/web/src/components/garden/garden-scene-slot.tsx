"use client";

import {
  DIMENSION_TO_PART,
  type EvidenceItem,
  type FocusTarget,
  type GroveId,
  type PrerequisiteEdge,
} from "@sg/contracts";
import {
  evidenceCardsFor,
  snapshotFromPlants,
  type EvidenceCardData,
  type GardenFocus,
} from "@sg/three";
import dynamic from "next/dynamic";
import { useCallback, useMemo, useState, useSyncExternalStore } from "react";

import { GardenMap2D, type GardenMapProps } from "./garden-map-2d";

/** The 3D scene touches `window` and WebGL, so it loads client-side only. */
const GardenScene = dynamic(() => import("@sg/three/scene").then((m) => m.GardenScene), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-sm text-foreground/60">
      Growing the garden…
    </div>
  ),
});

export interface GardenSceneSlotProps extends GardenMapProps {
  /** Evidence visible under the current filters and time travel; feeds the evidence cards. */
  evidence: EvidenceItem[];
  prerequisites?: PrerequisiteEdge[];
  /** Newest garden revision visible at `asOf`. */
  revision: number;
  ruleVersion: string;
}

const PART_TO_DIMENSION = Object.fromEntries(
  Object.entries(DIMENSION_TO_PART).map(([d, p]) => [p, d]),
) as Record<string, keyof typeof DIMENSION_TO_PART>;

/** Dashboard focus (plant keys) to the scene's focus (concept ids). They are the same strings. */
function toSceneFocus(focus: FocusTarget): GardenFocus {
  switch (focus.level) {
    case "garden":
      return focus;
    case "grove":
      return focus;
    case "plant":
      return { level: "plant", conceptId: focus.plantKey };
    case "part":
      return {
        level: "part",
        conceptId: focus.plantKey,
        part: DIMENSION_TO_PART[focus.part],
      };
  }
}

function fromSceneFocus(focus: GardenFocus): FocusTarget {
  switch (focus.level) {
    case "garden":
      return focus;
    case "grove":
      return { level: "grove", groveId: focus.groveId as GroveId };
    case "plant":
      return { level: "plant", plantKey: focus.conceptId };
    case "part": {
      const part = PART_TO_DIMENSION[focus.part];
      return part
        ? { level: "part", plantKey: focus.conceptId, part }
        : { level: "plant", plantKey: focus.conceptId };
    }
  }
}

let webglSupport: boolean | undefined;

function hasWebGL(): boolean {
  if (webglSupport !== undefined) return webglSupport;
  try {
    const canvas = document.createElement("canvas");
    webglSupport = Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    webglSupport = false;
  }
  return webglSupport;
}

const noSubscription = () => () => {};

/**
 * The dashboard's garden view: the real 3D scene from `@sg/three`, driven by the dashboard's
 * state. Clicks and keyboard in the scene call `onFocusChange`; nothing here mutates dashboard
 * state directly. Falls back to the flat 2D map when WebGL is unavailable, and the learner can
 * switch to it. The plants table below the scene remains the text alternative.
 */
export function GardenSceneSlot(props: GardenSceneSlotProps) {
  const { groves, plants, focus, onFocusChange, asOf, isTimeTravel, recentGrowthPlantKeys } = props;
  // `null` on the server and during hydration, then the real answer: no effect, no mismatch.
  const webgl = useSyncExternalStore<boolean | null>(noSubscription, hasWebGL, () => null);
  const [flat, setFlat] = useState(false);
  const [selected, setSelected] = useState<EvidenceCardData | null>(null);

  const snapshot = useMemo(
    () =>
      snapshotFromPlants({
        groves,
        plants,
        prerequisites: props.prerequisites,
        asOf,
        revision: props.revision,
        ruleVersion: props.ruleVersion,
      }),
    [groves, plants, props.prerequisites, asOf, props.revision, props.ruleVersion],
  );
  const sceneFocus = useMemo(() => toSceneFocus(focus), [focus]);
  const matched = useMemo(
    () =>
      plants.every((p) => p.matched)
        ? null
        : new Set(plants.filter((p) => p.matched).map((p) => p.meta.key)),
    [plants],
  );
  const pulse = useMemo(() => new Set(recentGrowthPlantKeys), [recentGrowthPlantKeys]);
  const evidenceFor = useCallback(
    (conceptId: string, part: Parameters<typeof evidenceCardsFor>[2]) =>
      evidenceCardsFor(props.evidence, conceptId, part),
    [props.evidence],
  );
  const changeFocus = useCallback(
    (next: GardenFocus) => {
      setSelected(null);
      onFocusChange(fromSceneFocus(next));
    },
    [onFocusChange],
  );

  if (webgl === false || flat) {
    return (
      <div className="flex flex-col gap-2">
        <GardenMap2D {...props} />
        {webgl && (
          <button
            type="button"
            onClick={() => setFlat(false)}
            className="self-end rounded-lg border border-white/10 px-2.5 py-1 text-xs text-foreground/70 outline-none hover:border-white/25 focus-visible:ring-2 focus-visible:ring-glow"
          >
            Show 3D garden
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        className="relative h-[70vh] min-h-[26rem] overflow-hidden rounded-2xl border border-white/10 bg-night sm:h-[80vh]"
        data-testid="garden-scene"
      >
        {webgl === null ? (
          <div className="flex h-full items-center justify-center text-sm text-foreground/60">
            Growing the garden…
          </div>
        ) : (
          <GardenScene
            snapshot={snapshot}
            focus={sceneFocus}
            onFocusChange={changeFocus}
            matchedConceptIds={matched}
            pulseConceptIds={pulse}
            evidence={evidenceFor}
            onEvidenceSelect={setSelected}
            timeOfDay={isTimeTravel ? 21 : undefined}
            quality="high"
            keyboard="focus"
            aria-label={`Garden as of ${asOf.slice(0, 10)}: ${plants.length} concept plants in ${groves.length} groves. The table below is a text version.`}
          />
        )}
        {isTimeTravel && (
          <span className="pointer-events-none absolute left-3 top-3 rounded-full bg-night/70 px-2.5 py-1 text-xs text-glow backdrop-blur">
            Replay · read only
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-start justify-between gap-2">
        {selected ? (
          <figure className="min-w-0 flex-1 rounded-xl bg-white/5 px-3 py-2 text-sm">
            <figcaption className="text-xs text-foreground/60">
              {selected.title} · {selected.independent ? "independent" : "assisted"} ·{" "}
              {selected.rubricVersion}
            </figcaption>
            <blockquote className="mt-1 whitespace-pre-wrap break-words text-foreground/90">
              {selected.excerpt}
            </blockquote>
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="mt-1 rounded px-1 text-xs text-glow outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-glow"
            >
              Close
            </button>
          </figure>
        ) : (
          <span />
        )}
        <button
          type="button"
          onClick={() => setFlat(true)}
          className="rounded-lg border border-white/10 px-2.5 py-1 text-xs text-foreground/70 outline-none hover:border-white/25 focus-visible:ring-2 focus-visible:ring-glow"
        >
          Show 2D map
        </button>
      </div>
    </div>
  );
}
