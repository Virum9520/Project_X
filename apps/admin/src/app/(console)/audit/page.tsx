import type { AuditPage } from "@sg/contracts";
import Link from "next/link";

import { ApiError, Badge, Card, PageHeader, Table, td } from "@/components/ui";
import { apiGet, query } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { requireOwner } from "@/lib/owner";

const PAGE_SIZE = 50;

export default async function AuditPage({ searchParams }: PageProps<"/audit">) {
  await requireOwner();
  const params = await searchParams;
  const text = (key: string) => (typeof params[key] === "string" ? (params[key] as string) : "");
  const action = text("action").slice(0, 100);
  const actor = text("actor").slice(0, 320);
  const before = text("before");

  const result = await apiGet<AuditPage>(
    `/v1/admin/audit${query({ action, actor, before, limit: PAGE_SIZE })}`,
  );

  return (
    <>
      <PageHeader
        title="Audit log"
        subtitle="Every admin mutation and test call: who, what, when, and the before and after state."
        actions={
          <form action="/audit" className="flex flex-wrap gap-2" role="search">
            <input
              name="action"
              defaultValue={action}
              placeholder="Action prefix, e.g. calls"
              aria-label="Filter by action prefix"
              className="w-48 rounded-lg border border-white/15 bg-night px-3 py-2 text-sm"
            />
            <input
              name="actor"
              defaultValue={actor}
              placeholder="Actor email"
              aria-label="Filter by actor email"
              className="w-48 rounded-lg border border-white/15 bg-night px-3 py-2 text-sm"
            />
            <button className="rounded-lg border border-white/15 px-4 py-2 text-sm hover:bg-white/5">
              Filter
            </button>
          </form>
        }
      />
      {!result.ok ? (
        <ApiError result={result} />
      ) : (
        <Card>
          <Table
            head={["When", "Actor", "Action", "Target", "Status", "Change"]}
            empty="No audit entries match."
          >
            {result.data.items.map((row) => (
              <tr key={row.id}>
                <td className={`${td} whitespace-nowrap`}>{dateTime(row.occurred_at)}</td>
                <td className={td}>
                  {row.actor_email ?? row.actor_type}
                  <div className="font-mono text-[10px] text-foreground/40">{row.request_id}</div>
                </td>
                <td className={`${td} font-mono text-xs`}>{row.action}</td>
                <td className={`${td} font-mono text-xs`}>
                  {row.target_type}
                  {row.target_id ? `:${row.target_id}` : ""}
                </td>
                <td className={td}>
                  {row.status_code !== null && (
                    <Badge tone={row.status_code < 400 ? "good" : "bad"}>{row.status_code}</Badge>
                  )}
                </td>
                <td className={td}>
                  {(row.before || row.after) && (
                    <details>
                      <summary className="cursor-pointer text-xs text-glow">Show</summary>
                      <pre className="mt-1 max-w-sm overflow-x-auto text-[11px] text-foreground/70">
                        {JSON.stringify({ before: row.before, after: row.after }, null, 2)}
                      </pre>
                    </details>
                  )}
                </td>
              </tr>
            ))}
          </Table>
          {result.data.next_before && (
            <nav className="mt-4 text-sm" aria-label="Pages">
              <Link
                href={
                  `/audit${query({ action, actor, before: result.data.next_before })}` as "/audit"
                }
                className="text-glow"
              >
                Older entries
              </Link>
            </nav>
          )}
        </Card>
      )}
    </>
  );
}
