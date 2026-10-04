import type { ReactNode } from "react";

import type { ApiResult } from "@/lib/api";

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-foreground/60">{subtitle}</p>}
      </div>
      {actions}
    </header>
  );
}

export function Card({
  title,
  note,
  children,
  className = "",
}: {
  title?: string;
  note?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-white/10 bg-dusk/60 p-5 ${className}`}>
      {title && (
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-medium uppercase tracking-wider text-foreground/70">
            {title}
          </h2>
          {note && <span className="text-xs text-foreground/50">{note}</span>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "good" | "warn" | "bad";
}) {
  const color = { default: "", good: "text-moss", warn: "text-ember", bad: "text-bloom" }[tone];
  return (
    <div className="rounded-xl border border-white/10 bg-dusk/60 p-4">
      <p className="text-xs uppercase tracking-wider text-foreground/50">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-foreground/50">{hint}</p>}
    </div>
  );
}

const BADGES = {
  good: "bg-moss/15 text-moss",
  warn: "bg-ember/15 text-ember",
  bad: "bg-bloom/15 text-bloom",
  neutral: "bg-white/10 text-foreground/70",
} as const;

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: keyof typeof BADGES;
  children: ReactNode;
}) {
  return <span className={`rounded-full px-2 py-0.5 text-xs ${BADGES[tone]}`}>{children}</span>;
}

export function callStateTone(state: string): keyof typeof BADGES {
  if (["completed", "connected"].includes(state)) return "good";
  if (["failed", "unknown", "missed", "busy", "unanswered"].includes(state)) return "bad";
  if (["ringing", "dispatching", "queued"].includes(state)) return "warn";
  return "neutral";
}

export function Table({
  head,
  children,
  empty,
}: {
  head: string[];
  children: ReactNode;
  empty?: string;
}) {
  const hasRows = Array.isArray(children) ? children.length > 0 : Boolean(children);
  if (!hasRows) return <p className="py-4 text-sm text-foreground/50">{empty ?? "Nothing yet."}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-white/10 text-xs uppercase tracking-wider text-foreground/50">
            {head.map((h) => (
              <th key={h} className="whitespace-nowrap py-2 pr-4 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-white/5">{children}</tbody>
      </table>
    </div>
  );
}

export const td = "py-2 pr-4 align-top";

/** Renders a failed API call as a calm in-page message instead of crashing the route. */
export function ApiError({ result }: { result: Extract<ApiResult<unknown>, { ok: false }> }) {
  const forbidden = result.status === 403;
  return (
    <div role="alert" className="rounded-xl border border-bloom/30 bg-bloom/5 p-5 text-sm">
      <p className="font-medium text-bloom">
        {forbidden ? "Your role can't see this" : "This data could not be loaded"}
      </p>
      <p className="mt-1 text-foreground/70">
        {result.status ? `The API answered ${result.status}: ` : ""}
        {result.detail}
      </p>
    </div>
  );
}

export function Freshness({ label, when, now }: { label: string; when: string | null; now: Date }) {
  const hours = when ? (now.getTime() - new Date(when).getTime()) / 3_600_000 : null;
  const tone = hours === null ? "neutral" : hours < 24 ? "good" : hours < 72 ? "warn" : "bad";
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-foreground/70">{label}</span>
      <Badge tone={tone}>
        {when
          ? new Date(when).toLocaleString("en-US", { timeZone: "UTC" }) + " UTC"
          : "no data yet"}
      </Badge>
    </div>
  );
}
