import { UserButton } from "@clerk/nextjs";
import type { AdminMe, Capability } from "@sg/contracts";

import { Nav, type NavItem } from "@/components/nav";
import { apiGet } from "@/lib/api";
import { requireOwner } from "@/lib/owner";

const ITEMS: (NavItem & { needs: Capability })[] = [
  { href: "/", label: "Overview", needs: "usage.read" },
  { href: "/users", label: "Users", needs: "users.read" },
  { href: "/costs", label: "Usage and costs", needs: "usage.read" },
  { href: "/calls", label: "Calls and agents", needs: "calls.read" },
  { href: "/quality", label: "Quality and ops", needs: "quality.read" },
  { href: "/assistant", label: "Ask the assistant", needs: "assistant.use" },
  { href: "/audit", label: "Audit log", needs: "audit.read" },
];

/** Every console page: allowlisted owner with a second factor verified in this session. */
export default async function ConsoleLayout({ children }: LayoutProps<"/">) {
  const { email } = await requireOwner();
  const me = await apiGet<AdminMe>("/v1/admin/me");
  // Hide what the API would refuse. If the API is down, show everything: pages explain the error.
  const allowed = me.ok ? new Set<Capability>(me.data.capabilities) : null;
  const items = ITEMS.filter((item) => allowed === null || allowed.has(item.needs));

  return (
    <div className="flex min-h-screen flex-1 flex-col md:flex-row">
      <aside className="border-b border-white/10 p-4 md:w-56 md:shrink-0 md:border-r md:border-b-0">
        <p className="px-3 pb-3 text-xs uppercase tracking-[0.3em] text-glow">Owner Console</p>
        <Nav items={items} />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-end gap-3 px-6 py-4 text-sm text-foreground/60">
          {email}
          <UserButton />
        </header>
        <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-6 pb-16">
          {children}
        </main>
      </div>
    </div>
  );
}
