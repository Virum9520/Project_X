"use client";

import type {
  FocusPlantArgs,
  FocusTarget,
  GardenDataset,
  GardenFilters,
  ScrubTimelineArgs,
  SetFilterArgs,
} from "@sg/contracts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { resolveFocusPlant, resolveScrub, resolveSetFilter } from "@/lib/garden/client-tools";
import {
  cutoffMs,
  hoursPracticed,
  independentRatio,
  plantsAt,
  readiness,
  reviewStats,
  stageCounts,
  timelineSeries,
  visibleEvidence,
} from "@/lib/garden/derive";
import { DEFAULT_STATE, type DashboardState, focusGrove, serializeState } from "@/lib/garden/state";

const TIMELINE_DAYS = 45;

/**
 * Dashboard state and derived views. One source of truth for the filters, the scrubber and the
 * zoom focus, mirrored into the URL (replaceState, so Back isn't polluted).
 *
 * Voice navigation: `clientTools` is shaped for ElevenLabs' `useConversation({ clientTools })`.
 * C12/Ask-Sanjaya passes it straight in; the handlers validate LLM arguments and return a short
 * sentence for the agent to speak.
 */
export function useGardenDashboard(dataset: GardenDataset, initial: DashboardState) {
  const [state, setState] = useState<DashboardState>(initial);

  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const qs = serializeState(state);
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [state]);

  const { filters, scrubDate } = state;

  const view = useMemo(() => {
    const cutoff = cutoffMs(dataset, scrubDate, filters);
    const plants = plantsAt(dataset, filters, cutoff);
    const matched = plants.filter((p) => p.matched);
    const visible = visibleEvidence(dataset, filters, cutoff);
    const visibleIds = new Set(visible.map((e) => e.id));
    const matchedKeys = new Set(matched.map((p) => p.meta.key));
    const growthEvents = dataset.growthEvents
      .filter((g) => g.evidenceIds.every((id) => visibleIds.has(id)) && matchedKeys.has(g.plantKey))
      .toSorted((a, b) => b.occurredAt.localeCompare(a.occurredAt));
    return {
      cutoff,
      plants,
      matched,
      evidence: visible,
      growthEvents,
      counts: stageCounts(matched),
      readiness: readiness(
        dataset,
        matched,
        filters.grove ? [filters.grove] : dataset.groves.map((g) => g.id),
      ),
      review: reviewStats(matched, cutoff),
      ratio: independentRatio(matched),
      hoursThisWeek: hoursPracticed(dataset, cutoff),
      isPast: scrubDate !== null,
    };
  }, [dataset, filters, scrubDate]);

  const evidenceFilterKey = `${filters.grove}|${filters.dimension}|${filters.character}|${filters.evidence}`;
  const series = useMemo(
    () =>
      timelineSeries(
        dataset,
        { ...filters, dateFrom: undefined, dateTo: undefined },
        Date.parse(dataset.generatedAt),
        TIMELINE_DAYS,
      ),
    // Date filters don't reshape the whole-history chart; the shaded range does.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dataset, evidenceFilterKey],
  );

  const setFilters = useCallback(
    (patch: Partial<GardenFilters>) =>
      setState((s) => ({ ...s, filters: { ...s.filters, ...patch } })),
    [],
  );
  const clearFilters = useCallback(
    () => setState((s) => ({ ...s, filters: { evidence: "all" } })),
    [],
  );
  const scrubTo = useCallback(
    (date: string | null) => setState((s) => ({ ...s, scrubDate: date })),
    [],
  );
  const focusOn = useCallback(
    (target: FocusTarget) => setState((s) => ({ ...s, focus: target })),
    [],
  );
  const zoomOut = useCallback(
    () =>
      setState((s) => {
        const f = s.focus;
        if (f.level === "part") return { ...s, focus: { level: "plant", plantKey: f.plantKey } };
        if (f.level === "plant") {
          const grove = focusGrove(f, dataset);
          return { ...s, focus: grove ? { level: "grove", groveId: grove } : { level: "garden" } };
        }
        return { ...s, focus: { level: "garden" } };
      }),
    [dataset],
  );
  const reset = useCallback(() => setState(DEFAULT_STATE), []);

  const clientTools = useMemo(
    () => ({
      focus_plant: (args: FocusPlantArgs) => {
        const r = resolveFocusPlant(dataset, args);
        if (r.ok) setState((s) => ({ ...s, focus: r.value }));
        return r.message;
      },
      set_filter: (args: SetFilterArgs = {}) => {
        const r = resolveSetFilter(dataset, args);
        if (r.ok) setState((s) => ({ ...s, filters: r.value }));
        return r.message;
      },
      scrub_timeline: (args: ScrubTimelineArgs) => {
        const r = resolveScrub(dataset, args);
        if (r.ok) setState((s) => ({ ...s, scrubDate: r.value }));
        return r.message;
      },
    }),
    [dataset],
  );

  return {
    state,
    view,
    series,
    actions: { setFilters, clearFilters, scrubTo, focusOn, zoomOut, reset },
    clientTools,
  };
}

export type GardenDashboardApi = ReturnType<typeof useGardenDashboard>;
