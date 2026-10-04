import type { AdminUserDetail } from "@sg/contracts";
import Link from "next/link";
import { notFound } from "next/navigation";

import { BarList, Meter } from "@/components/charts";
import { ApiError, Badge, Card, PageHeader, Stat, Table, td } from "@/components/ui";
import { apiGet } from "@/lib/api";
import { dateTime, duration, num, usd, WEEKDAYS } from "@/lib/format";
import { requireOwner } from "@/lib/owner";

export default async function UserPage({ params }: PageProps<"/users/[id]">) {
  await requireOwner();
  const { id } = await params;
  const result = await apiGet<AdminUserDetail>(`/v1/admin/users/${encodeURIComponent(id)}`);
  if (!result.ok && result.status === 404) notFound();
  if (!result.ok) {
    return (
      <>
        <PageHeader title="User" />
        <ApiError result={result} />
      </>
    );
  }
  const u = result.data;

  return (
    <>
      <PageHeader
        title={u.display_name ?? u.email_masked}
        subtitle={
          <>
            {u.email_masked} · joined {dateTime(u.created_at)}
            {u.deleted_at && <Badge tone="bad">deleted {dateTime(u.deleted_at)}</Badge>}
          </>
        }
        actions={
          <Link href="/users" className="text-sm text-glow">
            All users
          </Link>
        }
      />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Sessions" value={num(u.sessions_total)} />
        <Stat label="Spend this month" value={usd(u.spend_month_to_date_usd)} />
        <Stat
          label="Open disputes"
          value={num(u.open_disputes)}
          tone={u.open_disputes ? "warn" : "default"}
        />
        <Stat label="Timezone" value={u.timezone ?? "unset"} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Quota" note={u.budget.key}>
          <Meter label="Monthly budget" used={u.budget.committed_usd} limit={u.budget.limit_usd} />
          <h3 className="mb-2 mt-5 text-xs uppercase tracking-wider text-foreground/50">
            Spend by component
          </h3>
          <BarList
            rows={Object.entries(u.spend_by_component).map(([label, value]) => ({ label, value }))}
          />
        </Card>

        <Card title="Garden state" note="plants by status">
          <BarList
            format={num}
            rows={Object.entries(u.plant_status_counts)
              .map(([label, value]) => ({ label, value }))
              .sort((a, b) => b.value - a.value)}
          />
          <dl className="mt-5 grid grid-cols-2 gap-2 text-sm">
            <dt className="text-foreground/50">Major</dt>
            <dd>{u.major ?? "n/a"}</dd>
            <dt className="text-foreground/50">Experience</dt>
            <dd>{u.experience_level ?? "n/a"}</dd>
            <dt className="text-foreground/50">Target role</dt>
            <dd>{u.target_role ?? "n/a"}</dd>
            <dt className="text-foreground/50">Onboarded</dt>
            <dd>{u.onboarded_at ? dateTime(u.onboarded_at) : "not yet"}</dd>
          </dl>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Call enrollment">
          <Table head={["Channel", "Destination", "When", "Status"]} empty="Not enrolled.">
            {u.schedules.map((s) => (
              <tr key={s.id}>
                <td className={td}>{s.channel}</td>
                <td className={td}>
                  {s.destination_masked ?? "web"}{" "}
                  {s.channel === "phone" && (
                    <Badge tone={s.destination_verified ? "good" : "warn"}>
                      {s.destination_verified ? "verified" : "unverified"}
                    </Badge>
                  )}
                </td>
                <td className={td}>
                  {s.local_time} {s.tz}
                  <div className="text-xs text-foreground/50">
                    {s.days.map((d) => WEEKDAYS[d - 1]).join(" ")} · up to{" "}
                    {duration(s.max_duration_seconds)}
                  </div>
                </td>
                <td className={td}>
                  <Badge tone={s.enabled ? "good" : "neutral"}>
                    {s.enabled ? "enabled" : "paused"}
                  </Badge>
                </td>
              </tr>
            ))}
          </Table>
        </Card>

        <Card title="Voice consent">
          {u.voice_consent ? (
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <dt className="text-foreground/50">Version</dt>
              <dd>{u.voice_consent.consent_ver}</dd>
              <dt className="text-foreground/50">Phrase verified</dt>
              <dd>{u.voice_consent.phrase_verified ? "yes" : "no"}</dd>
              <dt className="text-foreground/50">Voice active</dt>
              <dd>{u.voice_consent.has_voice ? "yes" : "no"}</dd>
              <dt className="text-foreground/50">Given</dt>
              <dd>{dateTime(u.voice_consent.created_at)}</dd>
              <dt className="text-foreground/50">Revoked</dt>
              <dd>
                {u.voice_consent.revoked_at ? dateTime(u.voice_consent.revoked_at) : "not revoked"}
              </dd>
            </dl>
          ) : (
            <p className="text-sm text-foreground/50">No voice consent on file.</p>
          )}
        </Card>
      </div>

      <Card title="Recent sessions">
        <Table head={["When", "Agent", "Mode", "Status", "Length"]} empty="No sessions yet.">
          {u.recent_sessions.map((s) => (
            <tr key={s.id}>
              <td className={td}>{dateTime(s.started_at)}</td>
              <td className={td}>
                {s.character} {s.is_test && <Badge>test</Badge>}
              </td>
              <td className={td}>{s.mode}</td>
              <td className={td}>
                <Badge
                  tone={
                    s.status === "completed"
                      ? "good"
                      : ["failed", "interrupted"].includes(s.status)
                        ? "bad"
                        : "neutral"
                  }
                >
                  {s.status}
                </Badge>
              </td>
              <td className={td}>{duration(s.duration_seconds)}</td>
            </tr>
          ))}
        </Table>
      </Card>
    </>
  );
}
