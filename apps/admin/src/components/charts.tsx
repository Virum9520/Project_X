import { shortDate, usd } from "@/lib/format";

/** Horizontal bars for a ranked breakdown. Plain divs: readable, printable, no chart library. */
export function BarList({
  rows,
  format = usd,
}: {
  rows: { label: string; value: number; hint?: string }[];
  format?: (value: number) => string;
}) {
  const max = Math.max(...rows.map((r) => r.value), 0);
  if (rows.length === 0) return <p className="py-2 text-sm text-foreground/50">No data yet.</p>;
  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li key={row.label} className="text-sm">
          <div className="flex justify-between gap-3">
            <span className="truncate" title={row.label}>
              {row.label}
              {row.hint && <span className="ml-2 text-xs text-foreground/50">{row.hint}</span>}
            </span>
            <span className="tabular-nums text-foreground/80">{format(row.value)}</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-white/5">
            <div
              className="h-1.5 rounded-full bg-moss"
              style={{ width: `${max > 0 ? Math.max((row.value / max) * 100, 1) : 0}%` }}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** One bar per day, with a text table fallback for screen readers. */
export function DailyBars({ days }: { days: { day: string; usd: number }[] }) {
  if (days.length === 0)
    return <p className="py-2 text-sm text-foreground/50">No spend in range.</p>;
  const max = Math.max(...days.map((d) => d.usd), 0.000001);
  const width = 640;
  const height = 140;
  const gap = 3;
  const bar = Math.max((width - gap * (days.length - 1)) / days.length, 2);
  const first = days[0];
  const last = days[days.length - 1];
  return (
    <figure>
      <svg
        viewBox={`0 0 ${width} ${height + 18}`}
        role="img"
        aria-label={`Daily spend from ${first.day} to ${last.day}, peak ${usd(max)}`}
        className="w-full"
      >
        {days.map((d, i) => {
          const h = Math.max((d.usd / max) * height, 1);
          return (
            <rect
              key={d.day}
              x={i * (bar + gap)}
              y={height - h}
              width={bar}
              height={h}
              rx={2}
              className="fill-glow/70"
            >
              <title>{`${d.day}: ${usd(d.usd)}`}</title>
            </rect>
          );
        })}
        <text x={0} y={height + 14} className="fill-foreground/50 text-[10px]">
          {shortDate(first.day)}
        </text>
        <text x={width} y={height + 14} textAnchor="end" className="fill-foreground/50 text-[10px]">
          {shortDate(last.day)}
        </text>
      </svg>
      <figcaption className="sr-only">
        {days.map((d) => `${d.day}: ${usd(d.usd)}`).join("; ")}
      </figcaption>
    </figure>
  );
}

/** A used-of-limit meter. Turns amber at 70% and red at 90%. */
export function Meter({ used, limit, label }: { used: number; limit: number; label: string }) {
  const ratio = limit > 0 ? Math.min(used / limit, 1) : 0;
  const tone = ratio >= 0.9 ? "bg-bloom" : ratio >= 0.7 ? "bg-ember" : "bg-moss";
  return (
    <div>
      <div className="flex justify-between text-sm">
        <span>{label}</span>
        <span className="tabular-nums text-foreground/70">
          {usd(used)} of {usd(limit)}
        </span>
      </div>
      <div
        className="mt-1 h-2 rounded-full bg-white/5"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={used}
      >
        <div className={`h-2 rounded-full ${tone}`} style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}
