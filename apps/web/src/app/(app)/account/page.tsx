import type { Me } from "@sg/contracts";
import Link from "next/link";

import { EXPERIENCE_LABELS, GOAL_LABELS } from "@/app/onboarding/options";
import { apiGet } from "@/lib/api";
import { requireOnboardedLearner } from "@/lib/session";

export default async function AccountPage() {
  const { user, profile } = await requireOnboardedLearner();
  const me = await apiGet<Me>("/v1/me");

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-6 pb-16 pt-32">
      <header>
        <p className="text-sm uppercase tracking-[0.3em] text-glow">Your account</p>
        <h1 className="mt-2 text-3xl font-semibold">
          {user.firstName ?? user.primaryEmailAddress?.emailAddress}
        </h1>
      </header>

      <section className="grid gap-3 rounded-xl border border-white/10 bg-dusk/60 p-6 sm:grid-cols-2">
        <Field label="Studying" value={profile.major} />
        <Field label="Experience" value={EXPERIENCE_LABELS[profile.experience]} />
        <Field label="Time zone" value={profile.timezone.replaceAll("_", " ")} />
        <Field label="Goals" value={profile.goals.map((g) => GOAL_LABELS[g]).join(", ")} />
      </section>

      <section className="rounded-xl border border-white/10 bg-dusk/60 p-6">
        <h2 className="font-medium">Future-Self voice</h2>
        <p className="mt-2 text-sm text-foreground/70">
          Opt in to hear a daily message in your own voice, or delete your voice at any time.{" "}
          <Link href="/future-self" className="text-glow underline">
            Manage consent
          </Link>
        </p>
      </section>

      <section className="rounded-xl border border-white/10 bg-dusk/60 p-6">
        <h2 className="font-medium">Bhima check-in calls</h2>
        <p className="mt-2 text-sm text-foreground/70">
          Pick when Bhima rings you for a short accountability call.{" "}
          <Link href="/settings/schedule" className="text-glow underline">
            Call schedule
          </Link>
        </p>
      </section>

      <section className="rounded-xl border border-white/10 bg-dusk/60 p-6">
        <h2 className="font-medium">API connection</h2>
        {me.ok ? (
          <p className="mt-2 text-sm text-foreground/70">
            Verified by the API as <span className="font-mono">{me.data.user_id}</span>
            {me.data.console_access && " · owner-console access"}
          </p>
        ) : (
          <p className="mt-2 text-sm text-bloom">
            {me.status ? `API answered ${me.status}: ` : ""}
            {me.detail}
          </p>
        )}
      </section>
    </main>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-widest text-foreground/50">{label}</p>
      <p className="mt-1">{value}</p>
    </div>
  );
}
