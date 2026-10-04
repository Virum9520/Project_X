"use client";

import {
  CHARACTERS,
  type Character,
  type EvidenceDimension,
  type GardenDataset,
  type GardenFilters,
  type GroveId,
} from "@sg/contracts";
import type { ReactNode } from "react";

import { DIMENSION_FILTERS } from "@/lib/garden/state";

import { cap } from "./primitives";

const fieldClass =
  "w-full rounded-lg border border-white/10 bg-night/70 px-2.5 py-1.5 text-sm text-foreground outline-none transition focus-visible:border-glow focus-visible:ring-2 focus-visible:ring-glow/40";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-[0.65rem] uppercase tracking-[0.18em] text-foreground/50">
      {label}
      {children}
    </label>
  );
}

export function FiltersBar({
  dataset,
  filters,
  onChange,
  onClear,
  matchedCount,
}: {
  dataset: GardenDataset;
  filters: GardenFilters;
  onChange: (patch: Partial<GardenFilters>) => void;
  onClear: () => void;
  matchedCount: number;
}) {
  const active = [
    filters.grove,
    filters.dimension,
    filters.character,
    filters.dateFrom,
    filters.dateTo,
    filters.evidence === "independent_only" ? "i" : undefined,
  ].filter(Boolean).length;
  const independentOnly = filters.evidence === "independent_only";

  return (
    <form
      role="search"
      aria-label="Garden filters"
      className="glass grid grid-cols-2 items-end gap-3 rounded-2xl p-3 sm:p-4 md:grid-cols-4 xl:grid-cols-[repeat(5,minmax(0,1fr))_auto_auto]"
      onSubmit={(e) => e.preventDefault()}
    >
      <Field label="Domain">
        <select
          className={fieldClass}
          value={filters.grove ?? ""}
          onChange={(e) =>
            onChange({ grove: (e.target.value || undefined) as GroveId | undefined })
          }
        >
          <option value="">All domains</option>
          {dataset.groves.map((g) => (
            <option key={g.id} value={g.id}>
              {g.title}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Dimension">
        <select
          className={fieldClass}
          value={filters.dimension ?? ""}
          onChange={(e) =>
            onChange({ dimension: (e.target.value || undefined) as EvidenceDimension | undefined })
          }
        >
          <option value="">All dimensions</option>
          {DIMENSION_FILTERS.map((d) => (
            <option key={d} value={d}>
              {cap(d)}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Character">
        <select
          className={fieldClass}
          value={filters.character ?? ""}
          onChange={(e) =>
            onChange({ character: (e.target.value || undefined) as Character | undefined })
          }
        >
          <option value="">Everyone</option>
          {CHARACTERS.filter((c) => dataset.evidence.some((e) => e.character === c)).map((c) => (
            <option key={c} value={c}>
              {cap(c)}
            </option>
          ))}
        </select>
      </Field>
      <Field label="From">
        <input
          type="date"
          className={fieldClass}
          value={filters.dateFrom ?? ""}
          max={filters.dateTo ?? dataset.generatedAt.slice(0, 10)}
          onChange={(e) => onChange({ dateFrom: e.target.value || undefined })}
        />
      </Field>
      <Field label="To">
        <input
          type="date"
          className={fieldClass}
          value={filters.dateTo ?? ""}
          min={filters.dateFrom}
          max={dataset.generatedAt.slice(0, 10)}
          onChange={(e) => onChange({ dateTo: e.target.value || undefined })}
        />
      </Field>

      <button
        type="button"
        role="switch"
        aria-checked={independentOnly}
        onClick={() => onChange({ evidence: independentOnly ? "all" : "independent_only" })}
        className="col-span-2 flex items-center gap-2.5 rounded-lg border border-white/10 bg-night/70 px-3 py-2 text-left text-sm outline-none transition hover:border-white/25 focus-visible:ring-2 focus-visible:ring-glow/60 md:col-span-1"
      >
        <span
          aria-hidden
          className={`relative inline-block h-5 w-9 shrink-0 rounded-full transition ${independentOnly ? "bg-moss" : "bg-white/15"}`}
        >
          <span
            className={`absolute top-0.5 size-4 rounded-full bg-white transition-all ${independentOnly ? "left-[1.1rem]" : "left-0.5"}`}
          />
        </span>
        <span className="leading-tight">
          <span className="block">Independent only</span>
          <span className="block text-[0.65rem] text-foreground/50">
            {independentOnly ? "Assisted evidence hidden" : "Assisted shown separately"}
          </span>
        </span>
      </button>

      <div className="col-span-2 flex items-center justify-between gap-3 md:col-span-1 xl:justify-end">
        <p className="text-xs text-foreground/60" aria-live="polite">
          {matchedCount} plants shown
        </p>
        <button
          type="button"
          onClick={onClear}
          disabled={active === 0}
          className="rounded-lg px-3 py-1.5 text-sm text-glow outline-none transition hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-glow/60 disabled:cursor-default disabled:text-foreground/30 disabled:hover:bg-transparent"
        >
          Clear{active ? ` (${active})` : ""}
        </button>
      </div>
    </form>
  );
}
