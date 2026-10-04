"use client";

import type { GardenSnapshot, PlantPart } from "@sg/contracts";
import { Canvas } from "@react-three/fiber";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";

import { generateGardenLayout, layoutKey, type PathLayout } from "../generator/layout";
import { plantGrowth, plantVigor, type PlantGrowth } from "../model/growth";
import {
  describeFocus,
  focusConceptId,
  focusGroveId,
  GARDEN_FOCUS,
  moveSibling,
  sanitizeFocus,
  zoomIn,
  zoomOut,
} from "../model/navigation";
import type { EvidenceCardData, GardenFocus } from "../model/types";
import { atmosphereAt, localHour } from "./atmosphere";
import { GardenAtmosphere } from "./Sky";
import { CameraRig } from "./CameraRig";
import { Effects } from "./Effects";
import { Fireflies } from "./Fireflies";
import { framingFor } from "./framing";
import { Grove, groveStats } from "./Groves";
import { Island } from "./Island";
import { SceneLabels } from "./Labels";
import { createOverlayRegistry, OverlayProjector } from "./overlay";
import { Plant, type PlantInteraction } from "./Plant";
import { PrerequisitePaths } from "./PrerequisitePaths";

export type GardenQuality = "high" | "low";

export interface GardenSceneProps {
  /** Garden state to render. New revisions animate growth in place. */
  snapshot: GardenSnapshot;
  /** Generator seed (per learner). Same seed and structure always give the same garden. */
  seed?: string;
  /** Controlled semantic-zoom focus. Omit to let the scene manage focus itself. */
  focus?: GardenFocus;
  defaultFocus?: GardenFocus;
  onFocusChange?: (focus: GardenFocus) => void;
  /** Concepts matching the dashboard filters; the rest dim. `null`/omitted means all match. */
  matchedConceptIds?: ReadonlySet<string> | null;
  /** Concepts that just changed (e.g. live SSE growth); they glow and pulse. */
  pulseConceptIds?: ReadonlySet<string>;
  /** Evidence cards for a plant part, shown orbiting it at Part zoom. */
  evidence?: (conceptId: string, part: PlantPart) => EvidenceCardData[];
  onEvidenceSelect?: (card: EvidenceCardData) => void;
  /** Local hour (0–24) for the day-night cycle. Defaults to the viewer's clock. */
  timeOfDay?: number;
  /** `low` drops post-processing, shadows, elder trees and most grass. */
  quality?: GardenQuality;
  showLabels?: boolean;
  /** Slowly circle the island at Garden zoom when idle. */
  autoRotate?: boolean;
  /**
   * Keyboard navigation (Esc, arrows, Enter). `global` listens on the window so it works without
   * focusing the canvas (the garden is the dashboard's main view); `focus` only while the scene
   * has focus; `off` disables it. Keys typed into inputs are always ignored.
   */
  keyboard?: "global" | "focus" | "off";
  className?: string;
  style?: CSSProperties;
  "aria-label"?: string;
}

const visuallyHidden: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

/**
 * The 3D garden: a floating island where each grove is a domain and each plant a concept.
 * Click (or use the keyboard) to zoom Garden → Grove → Plant → Part. Esc zooms out, arrow keys
 * move between siblings, Enter zooms in.
 *
 * Client-only: render it from a `'use client'` wrapper via `next/dynamic(..., { ssr: false })`.
 */
export function GardenScene({
  snapshot,
  seed = "skill-garden",
  focus: controlledFocus,
  defaultFocus = GARDEN_FOCUS,
  onFocusChange,
  matchedConceptIds = null,
  pulseConceptIds,
  evidence,
  onEvidenceSelect,
  timeOfDay,
  quality = "high",
  showLabels = true,
  autoRotate = true,
  keyboard = "global",
  className,
  style,
  "aria-label": ariaLabel = "Skill garden",
}: GardenSceneProps) {
  const structure = layoutKey(snapshot, seed);
  // Placement depends only on structure, so new revisions reuse the layout.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const layout = useMemo(() => generateGardenLayout(snapshot, { seed }), [structure]);

  const growthById = useMemo(
    () => new Map(snapshot.plants.map((p) => [p.conceptId, plantGrowth(p)])),
    [snapshot],
  );
  const growthOf = useCallback(
    (id: string): PlantGrowth | undefined => growthById.get(id),
    [growthById],
  );

  const [innerFocus, setInnerFocus] = useState<GardenFocus>(defaultFocus);
  const focus = sanitizeFocus(controlledFocus ?? innerFocus, layout);
  const setFocus = useCallback(
    (next: GardenFocus) => {
      if (controlledFocus === undefined) setInnerFocus(next);
      onFocusChange?.(next);
    },
    [controlledFocus, onFocusChange],
  );

  const [hour] = useState(() => timeOfDay ?? localHour());
  const atmosphere = useMemo(() => atmosphereAt(timeOfDay ?? hour), [timeOfDay, hour]);
  const high = quality === "high";

  const focusedGrove = focusGroveId(focus, layout);
  const focusedPlant = focusConceptId(focus);
  const matches = useCallback(
    (conceptId: string) => !matchedConceptIds || matchedConceptIds.has(conceptId),
    [matchedConceptIds],
  );

  const statsByGrove = useMemo(
    () =>
      new Map(
        snapshot.groves.map((g) => [
          g.id,
          groveStats(snapshot.plants.filter((p) => p.groveId === g.id)),
        ]),
      ),
    [snapshot],
  );

  const vigorById = useMemo(
    () => new Map(snapshot.plants.map((p) => [p.conceptId, plantVigor(p)])),
    [snapshot],
  );
  const pathIntensity = useCallback(
    (path: PathLayout) => {
      const grown = (vigorById.get(path.from) ?? 0) > 0 ? 1 : 0.3;
      const filtered = matches(path.from) && matches(path.to) ? 1 : 0.2;
      const groveOf = (id: string) => layout.plants.get(id)?.groveId;
      let level = 0.75;
      if (focusedPlant) {
        const touches = path.from === focusedPlant || path.to === focusedPlant;
        const inGrove = groveOf(path.from) === focusedGrove || groveOf(path.to) === focusedGrove;
        level = touches ? 2.2 : inGrove ? 0.3 : 0.08;
      } else if (focusedGrove) {
        const inGrove = groveOf(path.from) === focusedGrove || groveOf(path.to) === focusedGrove;
        level = inGrove ? 1.3 : 0.15;
      }
      return level * grown * filtered;
    },
    [vigorById, matches, layout, focusedPlant, focusedGrove],
  );

  const handleKey = useCallback(
    (event: {
      key: string;
      target: EventTarget | null;
      defaultPrevented: boolean;
      preventDefault(): void;
    }) => {
      if (event.defaultPrevented) return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (target?.closest("input, textarea, select, [contenteditable='true'], [role='dialog']"))
        return;
      let next: GardenFocus | null = null;
      if (event.key === "Escape") next = zoomOut(focus, layout);
      else if (event.key === "ArrowRight" || event.key === "ArrowDown")
        next = moveSibling(focus, layout, 1);
      else if (event.key === "ArrowLeft" || event.key === "ArrowUp")
        next = moveSibling(focus, layout, -1);
      // Enter on a focused button activates the button instead.
      else if (event.key === "Enter" && !target?.closest("button, a")) next = zoomIn(focus, layout);
      if (!next) return;
      event.preventDefault();
      setFocus(next);
    },
    [focus, layout, setFocus],
  );
  useEffect(() => {
    if (keyboard !== "global") return;
    const listener = (event: globalThis.KeyboardEvent) => handleKey(event);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [keyboard, handleKey]);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (keyboard === "focus") handleKey(event);
  };

  const selectGrove = useCallback(
    (groveId: string) => setFocus({ level: "grove", groveId }),
    [setFocus],
  );
  const selectPlant = useCallback(
    (conceptId: string) => setFocus({ level: "plant", conceptId }),
    [setFocus],
  );
  const selectPart = useCallback(
    (conceptId: string, part: PlantPart) => setFocus({ level: "part", conceptId, part }),
    [setFocus],
  );

  const focusTarget = useMemo(
    () => framingFor(focus, layout, growthOf).target,
    [focus, layout, growthOf],
  );

  const evidenceCards = useMemo(
    () => (focus.level === "part" && evidence ? evidence(focus.conceptId, focus.part) : []),
    [focus, evidence],
  );
  const R = layout.islandRadius;
  const helpId = useId();
  const [overlay] = useState(createOverlayRegistry);
  const [orbit] = useState(() => ({ paused: false }));

  return (
    <div
      className={className}
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        overflow: "hidden",
        outline: "none",
        ...style,
      }}
      tabIndex={0}
      role="application"
      aria-roledescription="3D garden"
      aria-label={ariaLabel}
      aria-describedby={helpId}
      onKeyDown={onKeyDown}
    >
      <p id={helpId} style={visuallyHidden}>
        Enter zooms in, Escape zooms out, arrow keys move between groves, plants or plant parts.
      </p>
      <p aria-live="polite" style={visuallyHidden}>
        {describeFocus(focus, snapshot)}
      </p>
      <Canvas
        shadows={high ? "percentage" : false}
        dpr={[1, high ? 2 : 1.5]}
        camera={{ fov: 40, near: 0.1, far: R * 30, position: [0, R * 1.3, R * 2] }}
        gl={{ antialias: !high, powerPreference: "high-performance" }}
        onPointerMissed={() => setFocus(zoomOut(focus, layout))}
      >
        <GardenAtmosphere atmosphere={atmosphere} islandRadius={R} shadows={high} />
        <Island layout={layout} night={atmosphere.night} grassCount={high ? 9000 : 2500} />
        <PrerequisitePaths layout={layout} intensityFor={pathIntensity} />
        {layout.groves.map((grove) => {
          const stats = statsByGrove.get(grove.id) ?? { health: 0, plants: 0, grown: 0, due: 0 };
          return (
            <Grove
              key={grove.id}
              layout={layout}
              grove={grove}
              stats={stats}
              focused={focusedGrove === grove.id}
              dimmed={matchedConceptIds !== null && !grove.conceptIds.some(matches)}
              interactive={focus.level === "garden" || focusedGrove !== grove.id}
              elderTrees={high}
              onSelect={selectGrove}
            />
          );
        })}
        {snapshot.plants.map((plant) => {
          const plantLayout = layout.plants.get(plant.conceptId);
          if (!plantLayout) return null;
          const grove = layout.groveById.get(plantLayout.groveId);
          const isFocused = plant.conceptId === focusedPlant;
          const interaction: PlantInteraction = isFocused ? "parts" : "plant";
          return (
            <Plant
              key={plant.conceptId}
              plant={plant}
              layout={plantLayout}
              groveColor={grove?.color ?? "#6fd39c"}
              dimmed={!matches(plant.conceptId)}
              pulsing={pulseConceptIds?.has(plant.conceptId) ?? false}
              introDelay={0.3 + (grove?.index ?? 0) * 0.12 + plantLayout.slot * 0.06}
              interaction={interaction}
              focusedPart={isFocused && focus.level === "part" ? focus.part : null}
              onSelect={selectPlant}
              onSelectPart={selectPart}
            />
          );
        })}
        <Fireflies layout={layout} count={high ? 180 : 60} night={atmosphere.night} />
        <OverlayProjector registry={overlay} />
        <CameraRig layout={layout} focus={focus} growthOf={growthOf} autoRotate={autoRotate} />
        {high && (
          <Effects
            focusTarget={focusTarget}
            depthOfField={focus.level === "plant" || focus.level === "part"}
          />
        )}
      </Canvas>
      {showLabels && (
        <div style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden" }}>
          <SceneLabels
            registry={overlay}
            layout={layout}
            plants={snapshot.plants}
            growthOf={growthOf}
            statsByGrove={statsByGrove}
            focus={focus}
            focusedGrove={focusedGrove}
            matches={matches}
            evidenceCards={evidenceCards}
            orbit={orbit}
            onSelectGrove={selectGrove}
            onSelectPlant={selectPlant}
            onSelectPart={selectPart}
            onSelectEvidence={onEvidenceSelect}
          />
        </div>
      )}
    </div>
  );
}
