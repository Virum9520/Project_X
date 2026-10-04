import { redirect } from "next/navigation";

import { onboardingOf, requireLearner } from "@/lib/session";

import { OnboardingForm } from "./onboarding-form";

export default async function OnboardingPage() {
  const user = await requireLearner();
  if (onboardingOf(user)) redirect("/home");

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-10 px-6 pb-16 pt-32">
      <header className="flex flex-col gap-3">
        <p className="text-sm uppercase tracking-[0.3em] text-glow">
          Welcome{user.firstName ? `, ${user.firstName}` : ""}
        </p>
        <h1 className="text-3xl font-semibold">Let&apos;s plant your garden</h1>
        <p className="text-foreground/70">
          A few answers help your mentors start where you are. You can change them later.
        </p>
      </header>
      <OnboardingForm timezones={Intl.supportedValuesOf("timeZone")} />
    </main>
  );
}
