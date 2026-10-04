import type { QualityReport, SystemStatus } from "@sg/contracts";

import { BarList } from "@/components/charts";
import { ApiError, Badge, Card, PageHeader, Stat, Table, td } from "@/components/ui";
import { apiGet } from "@/lib/api";
import { dateTime, duration, num, pct } from "@/lib/format";
import { requireOwner } from "@/lib/owner";

export default async function QualityPage() {
  await requireOwner();
  const [quality, system] = await Promise.all([
    apiGet<QualityReport>("/v1/admin/quality"),
    apiGet<SystemStatus>("/v1/admin/system"),
  ]);

  return (
    <>
      <PageHeader
        title="Quality and operations"
        subtitle="Judge backlog, webhook health and system status."
      />
      {!quality.ok ? (
        <ApiError result={quality} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              label="Judge backlog"
              value={num(quality.data.judge_backlog)}
              hint={
                quality.data.oldest_pending_assessment_age_s === null
                  ? "nothing pending"
                  : `oldest waiting ${duration(quality.data.oldest_pending_assessment_age_s)}`
              }
              tone={quality.data.judge_backlog > 0 ? "warn" : "good"}
            />
            <Stat
              label="Judge disagreement"
              value={pct(quality.data.disagreement_rate)}
              hint={`${num(quality.data.disputes_upheld)} upheld of ${num(quality.data.resolved_disputes)} resolved disputes. Open: ${num(quality.data.open_disputes)}`}
            />
            <Stat
              label="Webhook lag"
              value={
                quality.data.webhook_oldest_unprocessed_age_s === null
                  ? "none"
                  : duration(quality.data.webhook_oldest_unprocessed_age_s)
              }
              hint={`avg processing ${duration(quality.data.webhook_avg_latency_s_24h)} (24h)`}
              tone={quality.data.webhook_oldest_unprocessed_age_s === null ? "good" : "warn"}
            />
            <Stat
              label="Sessions, 7d"
              value={`${num(quality.data.failed_sessions_7d)} failed`}
              hint={`${num(quality.data.interrupted_sessions_7d)} interrupted`}
              tone={quality.data.failed_sessions_7d ? "bad" : "good"}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Assessments by status">
              <BarList
                format={num}
                rows={Object.entries(quality.data.assessments_by_status).map(([label, value]) => ({
                  label,
                  value,
                }))}
              />
            </Card>
            <Card title="Provider webhooks by status">
              <BarList
                format={num}
                rows={Object.entries(quality.data.provider_events_by_status).map(
                  ([label, value]) => ({ label, value }),
                )}
              />
            </Card>
          </div>

          <Card title="Failed webhook events" note="dead letters, most recent first">
            <Table
              head={["Received", "Provider", "Type", "Attempts", "Error"]}
              empty="No failed events."
            >
              {quality.data.failed_events.map((e) => (
                <tr key={e.id}>
                  <td className={td}>{dateTime(e.received_at)}</td>
                  <td className={td}>{e.provider}</td>
                  <td className={td}>{e.event_type}</td>
                  <td className={`${td} tabular-nums`}>{e.attempts}</td>
                  <td
                    className={`${td} max-w-md truncate text-xs text-bloom`}
                    title={e.error ?? ""}
                  >
                    {e.error}
                  </td>
                </tr>
              ))}
            </Table>
          </Card>
        </>
      )}

      {!system.ok ? (
        <ApiError result={system} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card
            title="System health"
            note={`${system.data.environment}${system.data.git_sha ? ` · ${system.data.git_sha.slice(0, 7)}` : ""}`}
          >
            <ul className="space-y-2 text-sm">
              {system.data.components.map((c) => (
                <li key={c.name} className="flex items-center justify-between gap-3">
                  <span>{c.name.replaceAll("_", " ")}</span>
                  <span className="flex items-center gap-2">
                    {c.detail && <span className="text-xs text-foreground/50">{c.detail}</span>}
                    <Badge tone={c.ok ? "good" : "bad"}>{c.ok ? "ok" : "down"}</Badge>
                  </span>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Configuration" note="set or missing, never the values">
            <ul className="grid grid-cols-2 gap-2 text-sm">
              {Object.entries(system.data.configured).map(([name, set]) => (
                <li key={name} className="flex items-center justify-between gap-2">
                  <span className="truncate">{name.replaceAll("_", " ")}</span>
                  <Badge tone={set ? "good" : "neutral"}>{set ? "set" : "missing"}</Badge>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      )}
    </>
  );
}
