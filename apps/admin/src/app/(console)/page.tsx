import type { AdminOverview } from "@sg/contracts";

import { BarList, Meter } from "@/components/charts";
import { ApiError, Card, Freshness, PageHeader, Stat } from "@/components/ui";
import { apiGet } from "@/lib/api";
import { num, usd } from "@/lib/format";
import { requireOwner } from "@/lib/owner";

export default async function OverviewPage() {
  await requireOwner();
  const result = await apiGet<AdminOverview>("/v1/admin/overview");
  if (!result.ok) {
    return (
      <>
        <PageHeader title="Overview" />
        <ApiError result={result} />
      </>
    );
  }
  const o = result.data;
  const now = new Date(o.generated_at);
  const failures = o.failed_sessions_7d + o.failed_calls_7d + o.failed_provider_events;

  return (
    <>
      <PageHeader
        title="Overview"
        subtitle={`Skill Garden operations for ${o.period} (UTC). Spend counts each call once: ${o.cost_basis}.`}
      />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Active users (30 days)" value={num(o.active_users_30d)} />
        <Stat label="Completed sessions (30 days)" value={num(o.completed_sessions_30d)} />
        <Stat label="Spend this month" value={usd(o.spend_month_to_date_usd)} />
        <Stat
          label="Projected month end"
          value={usd(o.projected_month_end_usd)}
          hint="Linear run rate from spend so far"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Spend by cost center" note="month to date">
          <BarList
            rows={Object.entries(o.spend_by_cost_center)
              .map(([label, value]) => ({ label, value }))
              .sort((a, b) => b.value - a.value)}
          />
          {o.developer_budget && (
            <div className="mt-5">
              <Meter
                label="Developer test budget"
                used={o.developer_budget.committed_usd}
                limit={o.developer_budget.limit_usd}
              />
            </div>
          )}
        </Card>

        <Card title="Failures" note={failures === 0 ? "all clear" : "needs a look"}>
          <div className="grid grid-cols-3 gap-3">
            <Stat
              label="Sessions, 7d"
              value={num(o.failed_sessions_7d)}
              tone={o.failed_sessions_7d ? "bad" : "good"}
            />
            <Stat
              label="Calls, 7d"
              value={num(o.failed_calls_7d)}
              tone={o.failed_calls_7d ? "bad" : "good"}
            />
            <Stat
              label="Webhooks"
              value={num(o.failed_provider_events)}
              hint="failed, unresolved"
              tone={o.failed_provider_events ? "bad" : "good"}
            />
          </div>
        </Card>
      </div>

      <Card title="Data freshness" note="when each source last produced a row">
        <div className="space-y-2">
          <Freshness label="Usage events" when={o.freshness.usage_events_at} now={now} />
          <Freshness label="Cost entries" when={o.freshness.cost_entries_at} now={now} />
          <Freshness label="Sessions" when={o.freshness.sessions_at} now={now} />
          <Freshness label="Provider webhooks" when={o.freshness.provider_events_at} now={now} />
        </div>
      </Card>
    </>
  );
}
