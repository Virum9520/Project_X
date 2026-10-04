import type { Metadata } from "next";

import { IncomingCallListener } from "@/components/accountability/incoming-call-listener";
import { ScheduleSettings } from "@/components/accountability/schedule-settings";
import { requireOnboardedLearner } from "@/lib/session";

export const metadata: Metadata = { title: "Bhima call schedule · Skill Garden" };

export default async function ScheduleSettingsPage() {
  const { profile } = await requireOnboardedLearner();
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-6 pb-16 pt-32">
      <header>
        <p className="text-sm uppercase tracking-[0.3em] text-glow">Bhima · Accountability</p>
        <h1 className="mt-2 text-3xl font-semibold">Your check-in calls</h1>
        <p className="mt-3 text-foreground/70">
          Bhima rings you in the app at the times you pick, asks what you committed to, and checks
          one concept you learned a while ago. Calls are short, never during quiet hours, and you
          can stop them at any time.
        </p>
      </header>
      <ScheduleSettings defaultTz={profile.timezone} />
      <IncomingCallListener />
    </main>
  );
}
