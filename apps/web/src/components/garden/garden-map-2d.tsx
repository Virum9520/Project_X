"use client";

import type { FocusTarget, Grove, PlantState } from "@sg/contracts";
import { useMemo } from "react";

import { STAGE_META } from "./primitives";

/**
 * The flat 2D garden map: the fallback when WebGL is unavailable, and an opt-in view for people
 * who prefer it (`GardenSceneSlot` offers the toggle). It honours the same props as the 3D scene:
 *
 * - `plants` is the complete garden state *as of `asOf`*. `matched === false` plants render dimmed
 *   (a filter is active), never removed. `stage` drives the look; assisted-only plants are
 *   hatched, never drawn as independent; `wilting` means a review is overdue.
 * - `focus` is where the camera should be; clicking a grove, plant or part calls `onFocusChange`.
 *   It never mutates dashboard state directly.
 * - `recentGrowthPlantKeys` glow.
 */
export interface GardenMapProps {
  groves: Grove[];
  /** Every plant, as of `asOf`, with filter state in `matched`. */
  plants: PlantState[];
  focus: FocusTarget;
  onFocusChange: (target: FocusTarget) => void;
  /** ISO timestamp the state is as of (equals "now" unless time travel is active). */
  asOf: string;
  /** True while scrubbing the past; the scene should look read-only (e.g. dusk tint). */
  isTimeTravel: boolean;
  /** Plants that just grew; pulse or glow them. */
  recentGrowthPlantKeys?: string[];
}

const W = 600;
const H = 420;
const CX = W / 2;
const CY = H / 2;

interface Placed {
  plant: PlantState;
  x: number;
  y: number;
  r: number;
}

function layout(groves: Grove[], plants: PlantState[]) {
  const centers = new Map<string, { x: number; y: number }>();
  groves.forEach((g, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / groves.length;
    centers.set(g.id, { x: CX + Math.cos(a) * 200, y: CY + Math.sin(a) * 125 });
  });
  const placed: Placed[] = [];
  for (const g of groves) {
    const c = centers.get(g.id)!;
    plants
      .filter((p) => p.meta.grove === g.id)
      .forEach((plant, i) => {
        // Phyllotaxis spiral keeps each grove a tidy, deterministic cluster.
        const rad = 15 * Math.sqrt(i + 0.6);
        const ang = i * 2.399963;
        placed.push({
          plant,
          x: c.x + Math.cos(ang) * rad,
          y: c.y + Math.sin(ang) * rad * 0.8,
          r: 5.5 + plant.meta.difficulty * 0.8,
        });
      });
  }
  return { centers, placed };
}

function cameraFor(
  focus: FocusTarget,
  centers: Map<string, { x: number; y: number }>,
  placed: Placed[],
) {
  let scale = 1;
  let at = { x: CX, y: CY };
  if (focus.level === "grove") {
    scale = 2;
    at = centers.get(focus.groveId) ?? at;
  } else if (focus.level === "plant" || focus.level === "part") {
    const p = placed.find((q) => q.plant.meta.key === focus.plantKey);
    if (p) {
      scale = focus.level === "part" ? 4.2 : 3.2;
      at = p;
    }
  }
  return { scale, tx: CX - at.x * scale, ty: CY - at.y * scale };
}

export function GardenMap2D(props: GardenMapProps) {
  const { groves, plants, focus, onFocusChange, asOf, isTimeTravel, recentGrowthPlantKeys } = props;
  const { centers, placed } = useMemo(() => layout(groves, plants), [groves, plants]);
  const cam = cameraFor(focus, centers, placed);
  const recent = new Set(recentGrowthPlantKeys);
  const focusedKey = focus.level === "plant" || focus.level === "part" ? focus.plantKey : null;
  const focusedGrove =
    focus.level === "grove"
      ? focus.groveId
      : focusedKey
        ? plants.find((p) => p.meta.key === focusedKey)?.meta.grove
        : null;

  const moveSibling = (key: string, dir: 1 | -1) => {
    const me = placed.find((p) => p.plant.meta.key === key);
    if (!me) return;
    const siblings = placed.filter((p) => p.plant.meta.grove === me.plant.meta.grove);
    const next = siblings[(siblings.indexOf(me) + dir + siblings.length) % siblings.length];
    if (!next) return;
    onFocusChange({ level: "plant", plantKey: next.plant.meta.key });
    requestAnimationFrame(() => document.getElementById(`plant-${next.plant.meta.key}`)?.focus());
  };

  return (
    <div
      className={`relative overflow-hidden rounded-2xl border border-glow/20 ${
        isTimeTravel ? "bg-[#14122b]" : "bg-night/60"
      }`}
      data-testid="garden-map-2d"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 border-b border-glow/15 px-3 py-2 text-[0.65rem] uppercase tracking-[0.18em] text-glow/80">
        2D garden map
        <span className="normal-case tracking-normal text-foreground/50">
          Flat view of the same garden
        </span>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="block h-auto w-full"
        role="group"
        aria-label={`Garden map as of ${asOf.slice(0, 10)}. ${plants.length} concept plants in ${groves.length} groves. Use the table below for a text version.`}
      >
        <defs>
          <pattern
            id="slot-hatch"
            width="5"
            height="5"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <rect width="5" height="5" fill="#f2a65a" opacity="0.25" />
            <rect width="2" height="5" fill="#f2a65a" opacity="0.9" />
          </pattern>
          <radialGradient id="slot-island" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#1f2d52" />
            <stop offset="100%" stopColor="#0b1020" stopOpacity="0" />
          </radialGradient>
        </defs>
        <g
          className="garden-camera"
          style={{ transform: `translate(${cam.tx}px, ${cam.ty}px) scale(${cam.scale})` }}
        >
          <ellipse cx={CX} cy={CY} rx={285} ry={190} fill="url(#slot-island)" />
          {groves.map((g) => {
            const c = centers.get(g.id)!;
            const dim = focusedGrove && focusedGrove !== g.id;
            return (
              <g key={g.id} opacity={dim ? 0.35 : 1}>
                <circle
                  cx={c.x}
                  cy={c.y}
                  r={58}
                  fill="#9be7ff"
                  opacity={0.04}
                  stroke="#9be7ff"
                  strokeOpacity={0.15}
                  strokeDasharray="3 4"
                />
                <g
                  role="button"
                  tabIndex={0}
                  aria-label={`Zoom to ${g.title} grove`}
                  className="cursor-pointer outline-none [&:focus-visible>text]:fill-white"
                  onClick={() => onFocusChange({ level: "grove", groveId: g.id })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onFocusChange({ level: "grove", groveId: g.id });
                    }
                  }}
                >
                  <text
                    x={c.x}
                    y={c.y - 62}
                    textAnchor="middle"
                    fontSize={9}
                    fill="#a9b2c9"
                    letterSpacing={1.2}
                  >
                    {g.title.split(" & ")[0]!.toUpperCase()}
                  </text>
                </g>
              </g>
            );
          })}
          {placed.map(({ plant, x, y, r }) => {
            const key = plant.meta.key;
            const meta = STAGE_META[plant.stage];
            const selected = focusedKey === key;
            const dim = !plant.matched || (focusedGrove && focusedGrove !== plant.meta.grove);
            const assistedOnly = plant.stage === "assisted";
            const showLabel = focusedGrove === plant.meta.grove && focus.level !== "garden";
            return (
              <g
                key={key}
                id={`plant-${key}`}
                role="button"
                tabIndex={0}
                aria-pressed={selected}
                aria-label={`${plant.meta.title}: ${meta.label}${plant.wilting ? ", review overdue" : ""}${plant.matched ? "" : ", filtered out"}`}
                className="cursor-pointer outline-none [&:focus-visible>circle:first-child]:stroke-white"
                opacity={dim ? 0.2 : 1}
                onClick={() => onFocusChange({ level: "plant", plantKey: key })}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onFocusChange({ level: "plant", plantKey: key });
                  } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
                    e.preventDefault();
                    moveSibling(key, 1);
                  } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                    e.preventDefault();
                    moveSibling(key, -1);
                  }
                }}
              >
                {recent.has(key) && (
                  <circle
                    cx={x}
                    cy={y}
                    r={r + 5}
                    fill="none"
                    stroke="#9be7ff"
                    strokeWidth={1.5}
                    className="animate-ping"
                    style={{ transformOrigin: `${x}px ${y}px` }}
                  />
                )}
                <circle
                  cx={x}
                  cy={y}
                  r={r}
                  fill={assistedOnly ? "url(#slot-hatch)" : meta.color}
                  fillOpacity={plant.stage === "unassessed" ? 0.5 : 1}
                  stroke={
                    selected
                      ? "#fff"
                      : assistedOnly
                        ? "#f2a65a"
                        : plant.wilting
                          ? "#8a7f6a"
                          : "#0b1020"
                  }
                  strokeWidth={selected ? 1.6 : 1}
                  strokeDasharray={assistedOnly || plant.wilting ? "2.5 2" : undefined}
                />
                {plant.wilting && (
                  <path
                    d={`M${x - r * 0.5} ${y + r + 2} q ${r * 0.5} ${r * 0.9} ${r} 0`}
                    stroke="#8a7f6a"
                    strokeWidth={1.2}
                    fill="none"
                  />
                )}
                {showLabel && (
                  <text
                    x={x}
                    y={y + r + 8}
                    textAnchor="middle"
                    fontSize={4.2}
                    fill="#e8ecf6"
                    style={{ paintOrder: "stroke" }}
                    stroke="#0b1020"
                    strokeWidth={1.2}
                  >
                    {plant.meta.title.slice(0, 22)}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      <ul
        className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-white/5 px-3 py-2 text-[0.7rem] text-foreground/70"
        aria-label="Stage legend"
      >
        {(Object.keys(STAGE_META) as (keyof typeof STAGE_META)[]).map((s) => (
          <li key={s} className="inline-flex items-center gap-1.5">
            <span
              aria-hidden
              className={`inline-block size-2.5 rounded-full ${s === "assisted" ? "hatch" : ""}`}
              style={{
                background: s === "assisted" ? undefined : STAGE_META[s].color,
                outline: s === "assisted" ? "1px dashed #f2a65a" : undefined,
              }}
            />
            {STAGE_META[s].label}
          </li>
        ))}
        <li className="text-foreground/50">Dashed grey outline: wilting</li>
      </ul>
    </div>
  );
}
