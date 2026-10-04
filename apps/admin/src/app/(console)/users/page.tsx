import type { AdminUserPage } from "@sg/contracts";
import Link from "next/link";

import { ApiError, Badge, Card, PageHeader, Table, td } from "@/components/ui";
import { apiGet, query } from "@/lib/api";
import { dateTime, num, usd } from "@/lib/format";
import { requireOwner } from "@/lib/owner";

const PAGE_SIZE = 25;

export default async function UsersPage({ searchParams }: PageProps<"/users">) {
  await requireOwner();
  const params = await searchParams;
  const q = typeof params.q === "string" ? params.q.slice(0, 100) : "";
  const page = Math.max(1, Number(typeof params.page === "string" ? params.page : 1) || 1);

  const result = await apiGet<AdminUserPage>(
    `/v1/admin/users${query({ q, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE })}`,
  );

  return (
    <>
      <PageHeader
        title="Users"
        subtitle="Learners and their activity. Emails are masked; open a user for history, quota and call enrollment."
        actions={
          <form action="/users" className="flex gap-2" role="search">
            <input
              name="q"
              defaultValue={q}
              placeholder="Search email or name"
              aria-label="Search users"
              maxLength={100}
              className="w-64 rounded-lg border border-white/15 bg-night px-3 py-2 text-sm"
            />
            <button className="rounded-lg border border-white/15 px-4 py-2 text-sm hover:bg-white/5">
              Search
            </button>
          </form>
        }
      />
      {!result.ok ? (
        <ApiError result={result} />
      ) : (
        <Card note={`${num(result.data.total)} total`}>
          <Table
            head={["User", "Joined", "Onboarded", "Sessions", "Spend this month"]}
            empty={q ? `No users match "${q}".` : "No learners yet."}
          >
            {result.data.items.map((u) => (
              <tr key={u.id}>
                <td className={td}>
                  <Link
                    href={`/users/${u.id}`}
                    className="text-glow underline-offset-2 hover:underline"
                  >
                    {u.display_name ?? u.email_masked}
                  </Link>
                  {u.display_name && (
                    <span className="ml-2 text-xs text-foreground/50">{u.email_masked}</span>
                  )}
                </td>
                <td className={td}>{dateTime(u.created_at)}</td>
                <td className={td}>
                  <Badge tone={u.onboarded ? "good" : "neutral"}>
                    {u.onboarded ? "yes" : "no"}
                  </Badge>
                </td>
                <td className={`${td} tabular-nums`}>{num(u.sessions)}</td>
                <td className={`${td} tabular-nums`}>{usd(u.spend_month_to_date_usd)}</td>
              </tr>
            ))}
          </Table>
          <Pager
            q={q}
            page={page}
            hasMore={result.data.offset + result.data.items.length < result.data.total}
          />
        </Card>
      )}
    </>
  );
}

function Pager({ q, page, hasMore }: { q: string; page: number; hasMore: boolean }) {
  if (page === 1 && !hasMore) return null;
  const href = (p: number) => `/users${query({ q, page: p })}` as "/users";
  return (
    <nav className="mt-4 flex gap-3 text-sm" aria-label="Pages">
      {page > 1 && (
        <Link href={href(page - 1)} className="text-glow">
          Previous
        </Link>
      )}
      <span className="text-foreground/50">Page {page}</span>
      {hasMore && (
        <Link href={href(page + 1)} className="text-glow">
          Next
        </Link>
      )}
    </nav>
  );
}
