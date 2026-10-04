import type { AdminMe, CallNowOptions, CallRow, CallsReport } from "@sg/contracts";
import { randomUUID } from "node:crypto";

import { ApiError, Badge, Card, callStateTone, PageHeader, Stat, Table, td } from "@/components/ui";
import { apiGet } from "@/lib/api";
import { dateTime, duration, num } from "@/lib/format";
import { requireOwner } from "@/lib/owner";

import { CallNowForm } from "./call-now-form";

export default async function CallsPage() {
  await requireOwner();
  const [me, calls, options] = await Promise.all([
    apiGet<AdminMe>("/v1/admin/me"),
    apiGet<CallsReport>("/v1/admin/calls"),
    apiGet<CallNowOptions>("/v1/admin/calls/now/options"),
  ]);
  const canTrigger = me.ok && me.data.capabilities.includes("calls.trigger");

  return (
    <>
      <PageHeader
        title="Calls and agents"
        subtitle="Scheduled and test calls, their outcomes, and the agents behind them."
      />

      {canTrigger && options.ok && (
        <Card title="Call now" note="developer test call">
          <CallNowForm options={options.data} initialRequestId={randomUUID()} />
        </Card>
      )}
      {me.ok && !canTrigger && (
        <p className="text-sm text-foreground/50">
          Call now needs the calls.trigger capability, which this role does not have.
        </p>
      )}

      {!calls.ok ? (
        <ApiError result={calls} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {Object.entries(calls.data.state_counts_7d).map(([state, n]) => (
              <Stat key={state} label={`${state}, 7d`} value={num(n)} tone={countTone(state)} />
            ))}
          </div>
          <Card title="Active now">
            <CallTable rows={calls.data.active} empty="No calls in progress." />
          </Card>
          <Card title="Upcoming and queued">
            <CallTable rows={calls.data.upcoming} empty="Nothing scheduled." />
          </Card>
          <Card title="Recent outcomes">
            <CallTable rows={calls.data.recent} empty="No finished calls yet." />
          </Card>
        </>
      )}

      {options.ok ? (
        <Card title="Agents" note="last 30 days">
          <Table
            head={["Agent", "Agent ID", "Sessions", "Failed", "Test", "Avg length", "Versions"]}
          >
            {options.data.agents.map((a) => (
              <tr key={a.character}>
                <td className={td}>{a.character}</td>
                <td className={td}>
                  {a.configured ? (
                    <span className="font-mono text-xs">{a.agent_id}</span>
                  ) : (
                    <Badge tone="warn">not synced</Badge>
                  )}
                </td>
                <td className={`${td} tabular-nums`}>{num(a.sessions_30d)}</td>
                <td className={`${td} tabular-nums ${a.failed_30d ? "text-bloom" : ""}`}>
                  {num(a.failed_30d)}
                </td>
                <td className={`${td} tabular-nums`}>{num(a.test_sessions_30d)}</td>
                <td className={td}>{duration(a.avg_duration_seconds)}</td>
                <td className={`${td} text-xs text-foreground/60`}>
                  {a.versions.join(", ") || "n/a"}
                </td>
              </tr>
            ))}
          </Table>
        </Card>
      ) : (
        <ApiError result={options} />
      )}
    </>
  );
}

function countTone(state: string): "default" | "good" | "warn" | "bad" {
  const tone = callStateTone(state);
  return tone === "neutral" ? "default" : tone;
}

function CallTable({ rows, empty }: { rows: CallRow[]; empty: string }) {
  return (
    <Table head={["When", "Kind", "Learner", "Channel", "State", "Provider IDs"]} empty={empty}>
      {rows.map((c) => (
        <tr key={c.occurrence_id}>
          <td className={td}>{dateTime(c.scheduled_for)}</td>
          <td className={td}>
            <Badge tone={c.kind === "test" ? "warn" : "neutral"}>{c.kind}</Badge>
          </td>
          <td className={td}>{c.user_masked ?? "n/a"}</td>
          <td className={td}>{c.channel ?? "n/a"}</td>
          <td className={td}>
            <Badge tone={callStateTone(c.state)}>{c.state}</Badge>
            {c.error && <div className="mt-1 max-w-xs text-xs text-bloom">{c.error}</div>}
          </td>
          <td className={`${td} font-mono text-xs text-foreground/60`}>
            {c.el_conversation_id ?? ""}
            {c.twilio_call_sid ? ` ${c.twilio_call_sid}` : ""}
          </td>
        </tr>
      ))}
    </Table>
  );
}
