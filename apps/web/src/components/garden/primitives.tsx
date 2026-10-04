import {
  DIMENSION_TO_PART,
  type Dimension,
  type EvidenceKind,
  type PlantStage,
} from "@sg/contracts";
import type { ReactNode } from "react";

/** Stage presentation. Colour is never the only signal: every stage also has a label and glyph. */
export const STAGE_META: Record<
  PlantStage,
  { label: string; color: string; glyph: string; blurb: string }
> = {
  unassessed: { label: "Unassessed", color: "#4b5880", glyph: "·", blurb: "No evidence yet" },
  sprouting: { label: "Sprouting", color: "#7bd0e6", glyph: "◔", blurb: "First independent signs" },
  assisted: { label: "Assisted", color: "#f2a65a", glyph: "◐", blurb: "Only with hints" },
  independent: { label: "Independent", color: "#3fae7a", glyph: "●", blurb: "Done alone" },
  transfer: { label: "Transfer", color: "#b99cf5", glyph: "◆", blurb: "Applied in new settings" },
  retained: { label: "Retained", color: "#f4b8d4", glyph: "✿", blurb: "Still there after a gap" },
};

export const PART_LABEL: Record<Dimension, string> = {
  explanation: "Roots · explanation",
  application: "Stem · application",
  transfer: "Branches · transfer",
  retention: "Blossoms · retention",
};

export const partName = (d: Dimension) => DIMENSION_TO_PART[d];

export function Panel({
  title,
  action,
  children,
  className = "",
  id,
  labelledBy,
}: {
  title?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
  labelledBy?: string;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section
      id={id}
      aria-labelledby={labelledBy ?? headingId}
      className={`glass rounded-2xl p-4 sm:p-5 ${className}`}
    >
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          {title && (
            <h2
              id={headingId}
              className="text-[0.7rem] font-medium uppercase tracking-[0.22em] text-foreground/60"
            >
              {title}
            </h2>
          )}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

/** Independent evidence: solid. Assisted: dashed and hatched. Never merged, never colour-only. */
export function EvidenceBadge({
  kind,
  className = "",
}: {
  kind: EvidenceKind;
  className?: string;
}) {
  return kind === "independent" ? (
    <span
      className={`inline-flex items-center gap-1 rounded-full bg-moss/20 px-2 py-0.5 text-[0.7rem] font-medium text-moss ring-1 ring-moss/50 ${className}`}
    >
      <span aria-hidden className="size-1.5 rounded-full bg-moss" />
      Independent
    </span>
  ) : (
    <span
      className={`hatch inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.7rem] font-medium text-ember ${className}`}
      style={{ outline: "1px dashed rgb(242 166 90 / 0.7)", outlineOffset: "-1px" }}
    >
      <span aria-hidden>◐</span>
      Assisted
    </span>
  );
}

export function StageChip({ stage, wilting }: { stage: PlantStage; wilting?: boolean }) {
  const m = STAGE_META[stage];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span aria-hidden style={{ color: m.color }}>
        {m.glyph}
      </span>
      <span>{m.label}</span>
      {wilting && (
        <span className="rounded bg-wilt/30 px-1.5 py-px text-[0.65rem] text-foreground/80">
          wilting
        </span>
      )}
    </span>
  );
}

/** Independent score solid; assisted score hatched below it. Two bars, two numbers. */
export function DimensionBars({
  independent,
  assisted,
}: {
  independent: Record<Dimension, number | null>;
  assisted: Record<Dimension, number | null>;
}) {
  return (
    <dl className="space-y-3">
      {(Object.keys(PART_LABEL) as Dimension[]).map((d) => (
        <div key={d}>
          <dt className="mb-1 flex justify-between text-xs text-foreground/70">
            <span>{PART_LABEL[d]}</span>
          </dt>
          <dd className="space-y-1">
            <Bar label="Independent" value={independent[d]} kind="independent" />
            <Bar label="Assisted" value={assisted[d]} kind="assisted" />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Bar({ label, value, kind }: { label: string; value: number | null; kind: EvidenceKind }) {
  const pct = Math.round((value ?? 0) * 100);
  return (
    <div className="flex items-center gap-2">
      <span className="w-[4.5rem] shrink-0 text-[0.65rem] uppercase tracking-wide text-foreground/50">
        {label}
      </span>
      <div
        role="meter"
        aria-label={`${label} score`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={value === null ? "no evidence" : `${pct} percent`}
        className="h-2 flex-1 overflow-hidden rounded-full bg-white/5"
      >
        <div
          className={`h-full rounded-full ${kind === "independent" ? "bg-moss" : "hatch bg-ember/30"}`}
          style={{
            width: `${pct}%`,
            outline: kind === "assisted" ? "1px dashed rgb(242 166 90 / 0.8)" : undefined,
            outlineOffset: "-1px",
          }}
        />
      </div>
      <span className="w-9 text-right font-mono text-xs tabular-nums text-foreground/70">
        {value === null ? "–" : pct}
      </span>
    </div>
  );
}

export function formatDay(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

export const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
