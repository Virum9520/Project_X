import { SignOutButton, UserProfile } from "@clerk/nextjs";
import { redirect } from "next/navigation";

import { ownerAccess } from "@/lib/owner";

/** Where the console sends anyone who isn't yet an owner with a verified second factor. */
export default async function SecurityPage() {
  const access = await ownerAccess();
  if (access.status === "owner") redirect("/");

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col items-center gap-8 px-6 py-16 text-center">
      <p className="text-sm uppercase tracking-[0.3em] text-glow">Owner Console</p>
      {access.status === "forbidden" && (
        <Notice title="This account can't open the owner console">
          {access.email ?? "This account"} isn&apos;t on the owner list. Sign in with an owner
          account, or ask the owner for access.
        </Notice>
      )}
      {access.status === "mfa-setup" && (
        <>
          <Notice title="Turn on two-step verification">
            The owner console requires multi-factor authentication. Add an authenticator app under
            Security below, then sign out and sign back in using your second factor.
          </Notice>
          <UserProfile routing="hash" />
        </>
      )}
      {access.status === "mfa-reverify" && (
        <Notice title="Verify your second factor">
          This session was opened without your second factor. Sign out and sign back in, then
          complete the two-step verification prompt.
        </Notice>
      )}
      <SignOutButton redirectUrl="/sign-in">
        <button className="rounded-full border border-white/15 px-5 py-2 text-sm hover:bg-white/5">
          Sign out
        </button>
      </SignOutButton>
    </main>
  );
}

function Notice({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="max-w-xl">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-3 text-foreground/70">{children}</p>
    </div>
  );
}
