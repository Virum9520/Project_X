import type { ConsentStatus } from "@sg/contracts";
import type { Metadata } from "next";

import { apiGet } from "@/lib/api";
import { requireOnboardedLearner } from "@/lib/session";

import { FutureSelfPanel } from "./future-self-panel";

export const metadata: Metadata = { title: "Future-Self voice · Skill Garden" };

export default async function FutureSelfPage() {
  await requireOnboardedLearner();
  const status = await apiGet<ConsentStatus>("/v1/future-self/consent");

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-6 pb-16 pt-32">
      <header>
        <p className="text-sm uppercase tracking-[0.3em] text-glow">Krishna · Future-Self</p>
        <h1 className="mt-2 text-3xl font-semibold">A message from your future self</h1>
        <p className="mt-3 text-foreground/70">
          With your explicit consent, Skill Garden makes a copy of your voice and uses it for one
          thing only: a short daily message to you, from you, six months on. You can delete it at
          any time.
        </p>
      </header>
      {status.ok ? (
        <FutureSelfPanel initial={status.data} />
      ) : (
        <p role="alert" className="rounded-xl border border-bloom/40 bg-dusk/60 p-6 text-bloom">
          {status.status === 409
            ? "Open your account page once so your profile is ready, then come back."
            : `Voice settings are unavailable right now (${status.detail}).`}
        </p>
      )}
    </main>
  );
}
