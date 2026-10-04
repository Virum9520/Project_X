import { UserButton } from "@clerk/nextjs";

import { requireOwner } from "@/lib/owner";

/** Every console page: allowlisted owner with a second factor verified in this session. */
export default async function ConsoleLayout({ children }: LayoutProps<"/">) {
  const { email } = await requireOwner();
  return (
    <>
      <header className="flex items-center justify-end gap-3 px-6 py-4 text-sm text-foreground/60">
        {email}
        <UserButton />
      </header>
      {children}
    </>
  );
}
