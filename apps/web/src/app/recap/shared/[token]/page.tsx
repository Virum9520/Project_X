import type { RecapPayload } from "@sg/audio";
import type { Metadata } from "next";
import { notFound } from "next/navigation";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

// A private link: never indexed, never sends the token onward in a Referer header.
export const metadata: Metadata = {
  title: "Weekly recap · Skill Garden",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

/** A recap opened through a private link its owner created. The link itself is the credential. */
export default async function SharedRecapPage({ params }: PageProps<"/recap/shared/[token]">) {
  const { token } = await params;
  let recap: RecapPayload | null = null;
  try {
    const response = await fetch(`${API_URL}/v1/recap/shared/${encodeURIComponent(token)}`, {
      cache: "no-store",
    });
    if (response.ok) recap = (await response.json()) as RecapPayload;
  } catch {
    recap = null;
  }
  if (!recap) notFound();

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 px-4 pb-16 pt-16">
      <header>
        <p className="text-xs uppercase tracking-[0.3em] text-glow">Skill Garden · weekly recap</p>
        <h1 className="mt-1 text-2xl font-semibold">
          {recap.weekStart} to {recap.weekEnd}
        </h1>
      </header>
      {recap.audioUrl && <audio src={recap.audioUrl} controls preload="none" className="w-full" />}
      <ol className="flex flex-col gap-2" aria-label="Recap transcript">
        {recap.segments.map((s) => (
          <li key={s.id} className="rounded-xl bg-white/5 px-4 py-2 text-sm text-foreground/80">
            {s.text}
          </li>
        ))}
      </ol>
    </main>
  );
}
