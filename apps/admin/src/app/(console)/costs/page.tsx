import { COST_GROUP_BY, type CostGroupBy, type CostReport } from "@sg/contracts";
import Link from "next/link";

import { BarList, DailyBars } from "@/components/charts";
import { ApiError, Badge, Card, PageHeader, Stat, Table, td } from "@/components/ui";
import { apiGet, query } from "@/lib/api";
import { duration, num, pct, usd } from "@/lib/format";
import { requireOwner } from "@/lib/owner";

const GROUP_LABELS: Record<CostGroupBy, string> = {
  component: "Component",
  provider: "Provider",
  model: "Model",
  cost_center: "Cost center",
  user: "User",
};

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export default async function CostsPage({ searchParams }: PageProps<"/costs">) {
  await requireOwner();
  const params = await searchParams;
  const pick = (key: string) => {
    const value = params[key];
    return typeof value === "string" && DATE.test(value) ? value : undefined;
  };
  const start = pick("start");
  const end = pick("end");
  const requested = typeof params.group_by === "string" ? params.group_by : "component";
  const groupBy = (COST_GROUP_BY as readonly string[]).includes(requested)
    ? (requested as CostGroupBy)
    : "component";

  const result = await apiGet<CostReport>(
    `/v1/admin/costs${query({ start, end, group_by: groupBy })}`,
  );

  return (
    <>
      <PageHeader
        title="Usage and costs"
        subtitle="Spend per provider call from the usage ledger. Each call counts once: a reconciled cost replaces the estimate it superseded."
        actions={
          <form action="/costs" className="flex flex-wrap items-end gap-2">
            <input type="hidden" name="group_by" value={groupBy} />
            <label className="text-xs text-foreground/60">
              From
              <input
                type="date"
                name="start"
                defaultValue={result.ok ? result.data.start : start}
                className="mt-1 block rounded-lg border border-white/15 bg-night px-2 py-1.5 text-sm"
              />
            </label>
            <label className="text-xs text-foreground/60">
              To
              <input
                type="date"
                name="end"
                defaultValue={result.ok ? result.data.end : end}
                className="mt-1 block rounded-lg border border-white/15 bg-night px-2 py-1.5 text-sm"
              />
            </label>
            <button className="rounded-lg border border-white/15 px-4 py-1.5 text-sm hover:bg-white/5">
              Apply
            </button>
          </form>
        }
      />
      {!result.ok ? (
        <ApiError result={result} />
      ) : (
        <Report report={result.data} groupBy={groupBy} />
      )}
    </>
  );
}

function Report({ report, groupBy }: { report: CostReport; groupBy: CostGroupBy }) {
  const u = report.usage;
  const estimated = report.by_kind.estimated ?? 0;
  const unreported = u.events - u.token_reporting_events;
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Total spend"
          value={usd(report.total_usd)}
          hint={`${report.start} to ${report.end}`}
        />
        <Stat
          label="Confirmed share"
          value={pct(report.reconciled_share)}
          hint={`${usd(estimated)} still estimated`}
          tone={report.reconciled_share >= 0.8 ? "good" : "warn"}
        />
        <Stat
          label="Voice time"
          value={duration(u.connected_seconds)}
          hint={`${num(u.events)} usage events`}
        />
        <Stat
          label="Model tokens"
          value={`${num(u.input_tokens)} in / ${num(u.output_tokens)} out`}
          hint={
            unreported > 0
              ? `${num(unreported)} events did not report tokens (unknown, not zero)`
              : "all events reported"
          }
        />
      </div>

      <Card title="Daily spend">
        <DailyBars days={report.daily} />
      </Card>

      <Card
        title={`Cost by ${GROUP_LABELS[groupBy].toLowerCase()}`}
        note={
          <span className="flex flex-wrap gap-2">
            {COST_GROUP_BY.map((g) => (
              <Link
                key={g}
                href={
                  `/costs${query({ start: report.start, end: report.end, group_by: g })}` as "/costs"
                }
                aria-current={g === groupBy ? "true" : undefined}
                className={g === groupBy ? "text-foreground" : "text-glow"}
              >
                {GROUP_LABELS[g]}
              </Link>
            ))}
          </span>
        }
      >
        <div className="grid gap-6 lg:grid-cols-2">
          <BarList
            rows={report.groups.slice(0, 12).map((g) => ({ label: g.label, value: g.usd }))}
          />
          <Table
            head={[GROUP_LABELS[groupBy], "Entries", "Spend", "Share"]}
            empty="No spend in range."
          >
            {report.groups.map((g) => (
              <tr key={g.key}>
                <td className={`${td} max-w-56 truncate`} title={g.label}>
                  {g.label}
                </td>
                <td className={`${td} tabular-nums`}>{num(g.entries)}</td>
                <td className={`${td} tabular-nums`}>{usd(g.usd)}</td>
                <td className={`${td} tabular-nums`}>
                  {report.total_usd > 0 ? pct(g.usd / report.total_usd) : "n/a"}
                </td>
              </tr>
            ))}
          </Table>
        </div>
      </Card>

      <Card title="Cost basis" note={report.basis}>
        <div className="flex flex-wrap gap-4 text-sm">
          {Object.entries(report.by_kind).map(([kind, value]) => (
            <span key={kind} className="flex items-center gap-2">
              <Badge tone={kind === "estimated" ? "warn" : "good"}>{kind}</Badge>
              {usd(value)}
            </span>
          ))}
        </div>
        <p className="mt-3 text-xs text-foreground/50">
          Estimated costs come from the price book and are replaced when the provider reports or
          reconciles the real cost. Sandbox time: {duration(u.sandbox_seconds)}.
        </p>
      </Card>
    </>
  );
}
