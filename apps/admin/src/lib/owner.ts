import { auth, currentUser } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

/**
 * Server-side owner check for the console. The API repeats it on every admin request, so this
 * only decides what to render; it is never the security boundary on its own.
 */
const OWNER_EMAILS = new Set(
  (process.env.ADMIN_OWNER_EMAILS ?? "")
    .split(",")
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean),
);

export type OwnerAccess =
  | { status: "owner"; email: string }
  | { status: "forbidden"; email: string | null }
  | { status: "mfa-setup"; email: string }
  | { status: "mfa-reverify"; email: string };

export async function ownerAccess(): Promise<OwnerAccess> {
  const user = await currentUser();
  if (!user) {
    const { redirectToSignIn } = await auth();
    return redirectToSignIn();
  }
  const primary = user.primaryEmailAddress;
  const email =
    primary?.verification?.status === "verified" ? primary.emailAddress.toLowerCase() : null;
  if (!email || !OWNER_EMAILS.has(email)) return { status: "forbidden", email };
  if (!user.twoFactorEnabled) return { status: "mfa-setup", email };

  // fva = minutes since [first, second] factor verification; -1 means not in this session.
  const { factorVerificationAge } = await auth();
  if (!factorVerificationAge || factorVerificationAge[1] < 0)
    return { status: "mfa-reverify", email };
  return { status: "owner", email };
}

/** For console pages and server actions: an owner with MFA, or a redirect to the gate. */
export async function requireOwner() {
  const access = await ownerAccess();
  if (access.status !== "owner") redirect("/security");
  return access;
}
