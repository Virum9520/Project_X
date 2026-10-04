import { auth, currentUser } from "@clerk/nextjs/server";
import type { OnboardingProfile } from "@sg/contracts";
import { redirect } from "next/navigation";

/** The signed-in learner, or a redirect to sign-in. Call from every protected page and action. */
export async function requireLearner() {
  const user = await currentUser();
  if (!user) {
    const { redirectToSignIn } = await auth();
    return redirectToSignIn();
  }
  return user;
}

/**
 * The signed-in learner, or null. For Server Actions: a redirect is not a valid action response
 * (the browser reports "unexpected response"), so actions answer a signed-out caller themselves.
 */
export async function currentLearnerOrNull() {
  return (await currentUser()) ?? null;
}

export function onboardingOf(user: { publicMetadata: Record<string, unknown> }) {
  return (user.publicMetadata.onboarding as OnboardingProfile | undefined) ?? null;
}

/** The learner plus their onboarding answers; sends them to onboarding until it's done. */
export async function requireOnboardedLearner() {
  const user = await requireLearner();
  const profile = onboardingOf(user);
  if (!profile) redirect("/onboarding");
  return { user, profile };
}
