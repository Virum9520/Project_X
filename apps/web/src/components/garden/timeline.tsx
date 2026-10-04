"use client";

import { PLANT_STAGES, type PlantStage, type SessionMarker } from "@sg/contracts";
import { useMemo } from "react";

import type { TimelinePoint } from "@/lib/garden/derive";

import { Panel, STAGE_META, cap, formatDay } from "./primitives";

const W = 800;
const H = 160;
/** Bottom to top. "Unassessed" is the empty headroom above the stack. */
const STACK: PlantStage[] = ["retained", "transfer", "independent", "assisted", "sprouting"];

/**
 * Growth over time (stacked area by stage, the shape of a Tiger continuous aggregate), session
 * markers, and the time-travel scrubber. Dragging the slider replays the garden at that date.
 */
export function Timeline({
  series,
  sessions,
  scrubDate,
  onScrub,
  rangeFrom,
  rangeTo,
}: {
  series: TimelinePoint[];
  sessions: SessionMarker[];
  scrubDate: string | null;
  onScrub: (date: string | null) => void;
  rangeFrom?: string;
  rangeTo?: string;
}) {
  const last = series.length - 1;
  const idx = scrubDate
    ? Math.max(
        0,
        series.findIndex((p) => p.date === scrubDate),
      )
    : last;
  const current = series[idx]!;
  const total = PLANT_STAGES.reduce((s, k) => s + (series[0]?.counts[k] ?? 0), 0) || 1;
  const x = (i: number) => (i / Math.max(last, 1)) * W;
  const y = (v: number) => H - (v / total) * H;

  const areas = useMemo(() => {
    const cum = series.map(() => 0);
    return STACK.map((stage) => {
      const lower = [...cum];
      series.forEach((p, i) => (cum[i] = cum[i]! + p.counts[stage]));
      const top = series.map((_, i) => `${x(i).toFixed(1)},${y(cum[i]!).toFixed(1)}`);
      const bottom = series
        .map((_, i) => `${x(i).toFixed(1)},${y(lower[i]!).toFixed(1)}`)
        .reverse();
      return { stage, d: `M${top.join(" L")} L${bottom.join(" L")} Z` };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, total]);

  const byDay = useMemo(() => {
    const m = new Map<string, SessionMarker[]>();
    for (const s of sessions) {
      const d = s.startedAt.slice(0, 10);
      m.set(d, [...(m.get(d) ?? []), s]);
    }
    return m;
  }, [sessions]);

  const rangeIdx = (d?: string, fallback = 0) => {
    if (!d) return fallback;
    const i = series.findIndex((p) => p.date >= d);
    return i === -1 ? last : i;
  };
  const rFrom = rangeIdx(rangeFrom, 0);
  const rTo = rangeTo
    ? Math.max(
        0,
        series.findLastIndex((p) => p.date <= rangeTo),
      )
    : last;

  return (
    <Panel
      id="timeline"
      title="Growth over time"
      action={
        <div className="flex items-center gap-3 text-xs">
          <span aria-live="polite" className="text-foreground/70">
            {scrubDate ? `Viewing ${formatDay(current.date)}` : `Now · ${formatDay(current.date)}`}
          </span>
          {scrubDate && (
            <button
              type="button"
              onClick={() => onScrub(null)}
              className="rounded-lg bg-glow/15 px-2.5 py-1 text-glow outline-none hover:bg-glow/25 focus-visible:ring-2 focus-visible:ring-glow"
            >
              Back to now
            </button>
          )}
        </div>
      }
    >
      <div className="relative">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          className="block h-36 w-full sm:h-44"
          role="img"
          aria-label={`Stacked area chart of concepts by stage over the last ${series.length} days. On ${formatDay(current.date)}: ${STACK.map((s) => `${current.counts[s]} ${STAGE_META[s].label.toLowerCase()}`).join(", ")}.`}
        >
          <defs>
            <pattern
              id="tl-hatch"
              width="6"
              height="6"
              patternUnits="userSpaceOnUse"
              patternTransform="rotate(45)"
            >
              <rect width="6" height="6" fill="#f2a65a" opacity="0.25" />
              <rect width="2.5" height="6" fill="#f2a65a" opacity="0.85" />
            </pattern>
          </defs>
          {[0.25, 0.5, 0.75].map((f) => (
            <line
              key={f}
              x1={0}
              x2={W}
              y1={H * f}
              y2={H * f}
              stroke="white"
              strokeOpacity={0.06}
              vectorEffect="non-scaling-stroke"
            />
          ))}
          {(rangeFrom || rangeTo) && (
            <rect
              x={x(rFrom)}
              width={Math.max(x(rTo) - x(rFrom), 2)}
              y={0}
              height={H}
              fill="#9be7ff"
              opacity={0.07}
            />
          )}
          {areas.map(({ stage, d }) => (
            <path
              key={stage}
              d={d}
              fill={stage === "assisted" ? "url(#tl-hatch)" : STAGE_META[stage].color}
              fillOpacity={stage === "assisted" ? 1 : 0.85}
              stroke={STAGE_META[stage].color}
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
              strokeDasharray={stage === "assisted" ? "4 3" : undefined}
            />
          ))}
          <line
            x1={x(idx)}
            x2={x(idx)}
            y1={0}
            y2={H}
            stroke="white"
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
          />
        </svg>

        <ul className="relative mt-1 h-6" aria-label="Sessions">
          {series.map((p, i) => {
            const ss = byDay.get(p.date);
            if (!ss) return null;
            return (
              <li
                key={p.date}
                className="absolute -translate-x-1/2"
                style={{ left: `${(i / Math.max(last, 1)) * 100}%` }}
              >
                <button
                  type="button"
                  onClick={() => onScrub(i === last ? null : p.date)}
                  title={ss.map((s) => `${s.title} (${s.minutes} min)`).join("\n")}
                  aria-label={`${ss.length} session${ss.length > 1 ? "s" : ""} on ${formatDay(p.date)}: ${ss.map((s) => s.title).join("; ")}. Show the garden on this day.`}
                  className="grid size-6 place-items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-glow"
                >
                  <span className="size-2 rounded-full bg-glow/80 ring-2 ring-night" />
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      <label className="mt-1 block">
        <span className="sr-only">Time travel: choose a day to see the garden as it was</span>
        <input
          type="range"
          min={0}
          max={last}
          step={1}
          value={idx}
          onChange={(e) => {
            const i = Number(e.target.value);
            onScrub(i === last ? null : series[i]!.date);
          }}
          aria-valuetext={formatDay(current.date)}
          className="h-6 w-full cursor-pointer accent-[#9be7ff]"
        />
      </label>
      <div className="flex justify-between text-[0.7rem] text-foreground/50">
        <span>{formatDay(series[0]!.date)}</span>
        <span>Drag to time-travel · read-only replay of past revisions</span>
        <span>{formatDay(series[last]!.date)}</span>
      </div>

      <ul
        className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs"
        aria-label="Counts at the selected day"
      >
        {[...STACK].reverse().map((s) => (
          <li key={s} className="inline-flex items-center gap-1.5 text-foreground/70">
            <span
              aria-hidden
              className={`size-2.5 rounded-sm ${s === "assisted" ? "hatch" : ""}`}
              style={{
                background: s === "assisted" ? undefined : STAGE_META[s].color,
                outline: s === "assisted" ? "1px dashed #f2a65a" : undefined,
              }}
            />
            {cap(s)}{" "}
            <span className="font-mono tabular-nums text-foreground">{current.counts[s]}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
