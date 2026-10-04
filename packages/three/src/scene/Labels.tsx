"use client";

import type { PlantPart, PlantSnapshot } from "@sg/contracts";
import { useMemo, type ReactNode } from "react";
import * as THREE from "three";

import type { GardenLayout } from "../generator/layout";
import { PART_TO_DIMENSION, PLANT_PARTS, type PlantGrowth } from "../model/growth";
import type { EvidenceCardData, GardenFocus } from "../model/types";
import { partAnchor, plantTop } from "./anchors";
import type { GroveStats } from "./Groves";
import { OverlayItem, type OverlayRegistry } from "./overlay";
import { buttonReset, cardStyle, chipStyle, groveLabelStyle, labelStyle } from "./styles";

/** In-scene HTML: grove labels, plant labels, part chips and orbiting evidence cards. */

const STATUS_LABEL: Record<PlantSnapshot["status"], string> = {
  unassessed: "seed",
  sprouting: "sprouting",
  assisted: "assisted",
  independent: "independent",
  transfer: "transfer",
  retained: "retained",
  due: "review due",
  wilting: "wilting",
};

const KIND_LABEL: Record<EvidenceCardData["kind"], string> = {
  transcript: "Transcript",
  code: "Code",
  test: "Tests",
};

const pct = (value: number) => `${Math.round(value * 100)}%`;

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export interface SceneLabelsProps {
  registry: OverlayRegistry;
  layout: GardenLayout;
  plants: PlantSnapshot[];
  growthOf: (conceptId: string) => PlantGrowth | undefined;
  statsByGrove: Map<string, GroveStats>;
  focus: GardenFocus;
  focusedGrove: string | null;
  matches: (conceptId: string) => boolean;
  evidenceCards: EvidenceCardData[];
  orbit: { paused: boolean };
  onSelectGrove: (groveId: string) => void;
  onSelectPlant: (conceptId: string) => void;
  onSelectPart: (conceptId: string, part: PlantPart) => void;
  onSelectEvidence?: (card: EvidenceCardData) => void;
}

const ORBIT_RADIUS = 0.95;
const ORBIT_SPEED = 0.12;

export function SceneLabels({
  registry,
  layout,
  plants,
  growthOf,
  statsByGrove,
  focus,
  focusedGrove,
  matches,
  evidenceCards,
  orbit,
  onSelectGrove,
  onSelectPlant,
  onSelectPart,
  onSelectEvidence,
}: SceneLabelsProps) {
  const focusedPlant = focus.level === "plant" || focus.level === "part" ? focus.conceptId : null;
  const focusedPart = focus.level === "part" ? focus.part : null;

  // Orbit angle accumulates only while not paused, so hovering a card holds it still.
  const orbitClock = useMemo(() => ({ angle: 0, last: 0 }), []);
  const orbitAngle = (elapsed: number) => {
    const dt = Math.min(0.1, Math.max(0, elapsed - orbitClock.last));
    orbitClock.last = elapsed;
    if (!orbit.paused) orbitClock.angle += dt * ORBIT_SPEED;
    return orbitClock.angle;
  };

  const items: ReactNode[] = [];

  if (focus.level === "garden") {
    for (const grove of layout.groves) {
      const stats = statsByGrove.get(grove.id);
      if (!stats) continue;
      const [cx, cy, cz] = grove.center;
      const dimmed = !grove.conceptIds.some(matches);
      items.push(
        <OverlayItem
          key={`grove:${grove.id}`}
          registry={registry}
          id={`grove:${grove.id}`}
          anchor={{ position: new THREE.Vector3(cx, cy + 3.2, cz) }}
        >
          <button
            type="button"
            style={{ ...buttonReset, ...groveLabelStyle, opacity: dimmed ? 0.5 : 1 }}
            onClick={() => onSelectGrove(grove.id)}
          >
            <span style={{ display: "block", fontWeight: 600 }}>{grove.label}</span>
            <span
              style={{
                display: "block",
                height: 4,
                borderRadius: 2,
                background: "rgba(255,255,255,0.12)",
                margin: "6px 0 4px",
              }}
            >
              <span
                style={{
                  display: "block",
                  height: "100%",
                  width: pct(stats.health),
                  borderRadius: 2,
                  background: grove.color,
                }}
              />
            </span>
            <span style={{ display: "block", opacity: 0.7, fontSize: 11 }}>
              {stats.grown}/{stats.plants} growing{stats.due > 0 ? ` · ${stats.due} due` : ""}
            </span>
          </button>
        </OverlayItem>,
      );
    }
  }

  if (focus.level === "grove") {
    for (const plant of plants) {
      const plantLayout = layout.plants.get(plant.conceptId);
      const growth = growthOf(plant.conceptId);
      if (!plantLayout || !growth || plantLayout.groveId !== focusedGrove) continue;
      const top = plantTop(plantLayout, growth);
      items.push(
        <OverlayItem
          key={`plant:${plant.conceptId}`}
          registry={registry}
          id={`plant:${plant.conceptId}`}
          anchor={{ position: top.setY(top.y + 0.35), offset: [0, -10] }}
        >
          <button
            type="button"
            style={{ ...buttonReset, ...labelStyle, opacity: matches(plant.conceptId) ? 1 : 0.45 }}
            onClick={() => onSelectPlant(plant.conceptId)}
          >
            {plant.label}
            <span style={{ opacity: 0.6, marginLeft: 6 }}>{STATUS_LABEL[plant.status]}</span>
          </button>
        </OverlayItem>,
      );
    }
  }

  if (focusedPlant) {
    const plant = plants.find((p) => p.conceptId === focusedPlant);
    const plantLayout = layout.plants.get(focusedPlant);
    const growth = growthOf(focusedPlant);
    const color = layout.groveById.get(plantLayout?.groveId ?? "")?.color ?? "#9be7ff";
    if (plant && plantLayout && growth) {
      for (const part of PLANT_PARTS) {
        const score = plant.dimensions[PART_TO_DIMENSION[part]];
        const active = focusedPart === part;
        if (focusedPart && !active) continue;
        // Only parts that have grown get a chip (roots always do, as the entry point).
        if (part !== "roots" && !active && growth.parts[part].total === 0) continue;
        const side = part === "roots" || part === "branches" ? 1 : -1;
        items.push(
          <OverlayItem
            key={`part:${part}`}
            registry={registry}
            id={`part:${part}`}
            anchor={{
              position: partAnchor(plantLayout, part, growth),
              offset: active ? [0, -70] : [side * 120, part === "roots" ? 18 : 0],
            }}
          >
            <button
              type="button"
              aria-pressed={active}
              style={{
                ...buttonReset,
                ...chipStyle,
                borderColor: active ? color : "rgba(155, 231, 255, 0.18)",
                background: active ? "rgba(26, 35, 64, 0.92)" : chipStyle.background,
              }}
              onClick={() => onSelectPart(plant.conceptId, part)}
            >
              <strong style={{ textTransform: "capitalize" }}>{part}</strong>
              <span style={{ opacity: 0.65 }}> · {PART_TO_DIMENSION[part]} </span>
              {pct(score.independent)}
              {score.assisted > score.independent && (
                <span style={{ opacity: 0.6 }}>
                  {" "}
                  (+{pct(score.assisted - score.independent)} assisted)
                </span>
              )}
            </button>
          </OverlayItem>,
        );
      }

      if (focusedPart) {
        const center = partAnchor(plantLayout, focusedPart, growth);
        const point = new THREE.Vector3();
        evidenceCards.forEach((card, i) => {
          const phase = (i / evidenceCards.length) * Math.PI * 2;
          const lift = 0.1 + (i % 2) * 0.3;
          items.push(
            <OverlayItem
              key={`evidence:${card.id}`}
              registry={registry}
              id={`evidence:${card.id}`}
              anchor={{
                position: (elapsed) => {
                  const a = phase + orbitAngle(elapsed);
                  return point.set(
                    center.x + Math.cos(a) * ORBIT_RADIUS,
                    center.y + lift,
                    center.z + Math.sin(a) * ORBIT_RADIUS,
                  );
                },
              }}
            >
              <EvidenceCard
                card={card}
                color={color}
                onSelect={onSelectEvidence}
                onHold={(held) => {
                  orbit.paused = held;
                }}
              />
            </OverlayItem>,
          );
        });
      }
    }
  }

  return <>{items}</>;
}

function EvidenceCard({
  card,
  color,
  onSelect,
  onHold,
}: {
  card: EvidenceCardData;
  color: string;
  onSelect?: (card: EvidenceCardData) => void;
  onHold: (held: boolean) => void;
}) {
  return (
    <button
      type="button"
      style={{ ...buttonReset, ...cardStyle, borderColor: color }}
      onClick={() => onSelect?.(card)}
      onPointerEnter={() => onHold(true)}
      onPointerLeave={() => onHold(false)}
      onFocus={() => onHold(true)}
      onBlur={() => onHold(false)}
    >
      <span
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 8,
          opacity: 0.75,
          fontSize: 11,
        }}
      >
        <span style={{ textTransform: "capitalize" }}>
          {KIND_LABEL[card.kind]} · {card.character}
        </span>
        <span>{formatDate(card.occurredAt)}</span>
      </span>
      {/* Transcripts and code are data: rendered as text, never as markup. */}
      <span
        style={{
          display: "-webkit-box",
          WebkitLineClamp: 4,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
          whiteSpace: "pre-wrap",
          margin: "6px 0 8px",
          fontFamily:
            card.kind === "transcript"
              ? "inherit"
              : "var(--font-geist-mono, ui-monospace, monospace)",
        }}
      >
        {card.excerpt}
      </span>
      <span style={{ display: "flex", gap: 6, fontSize: 11, alignItems: "center" }}>
        <span
          style={{
            padding: "1px 7px",
            borderRadius: 999,
            background: card.independent ? "rgba(63, 174, 122, 0.25)" : "rgba(155, 231, 255, 0.15)",
            border: `1px ${card.independent ? "solid #3fae7a" : "dashed #9be7ff"}`,
          }}
        >
          {card.independent ? "Independent" : "Assisted"}
        </span>
        <span style={{ opacity: 0.65 }}>
          ±{Math.round(card.uncertainty * 100)}% · {card.rubricVersion}
        </span>
      </span>
    </button>
  );
}
