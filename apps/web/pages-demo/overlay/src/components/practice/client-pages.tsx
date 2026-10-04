"use client";

import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

/**
 * The static site's interactive pages load in the browser only: they read this browser's
 * practice records and today's date, use speech and run code, none of which exists at build time.
 */

function PageLoading() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 pb-16 pt-28 sm:px-6">
      <div className="grid min-h-60 place-items-center rounded-2xl border border-white/10 text-sm text-foreground/60">
        <span className="flex items-center gap-2">
          <span className="size-2 animate-pulse rounded-full bg-glow" aria-hidden />
          Loading…
        </span>
      </div>
    </main>
  );
}

export const GardenClient = dynamic(() => import("./garden-pages").then((m) => m.GardenPage), {
  ssr: false,
  loading: PageLoading,
});
export const HomeClient = dynamic(() => import("./garden-pages").then((m) => m.HomePage), {
  ssr: false,
  loading: PageLoading,
});
export const SessionsClient = dynamic(() => import("./garden-pages").then((m) => m.SessionsPage), {
  ssr: false,
  loading: PageLoading,
});
export const RecapClient = dynamic(() => import("./garden-pages").then((m) => m.RecapPage), {
  ssr: false,
  loading: PageLoading,
});
export const LabClient = dynamic(() => import("./garden-pages").then((m) => m.LabPage), {
  ssr: false,
  loading: PageLoading,
});
export const DronaClient = dynamic(() => import("./drona-session").then((m) => m.DronaSession), {
  ssr: false,
  loading: PageLoading,
});
export const ArjunaClient = dynamic(
  () => import("./arjuna-interview").then((m) => m.ArjunaInterview),
  { ssr: false, loading: PageLoading },
);
export const PrepareClient = dynamic(
  () => import("./prepare-plan").then((m) => m.PreparePlanPage),
  { ssr: false, loading: PageLoading },
);
export const BhimaClient = dynamic(() => import("./bhima-call").then((m) => m.BhimaPage), {
  ssr: false,
  loading: PageLoading,
});
export const KrishnaClient = dynamic(() => import("./krishna-message").then((m) => m.KrishnaPage), {
  ssr: false,
  loading: PageLoading,
});
const ViduraClient = dynamic(() => import("./vidura-interview").then((m) => m.ViduraInterview), {
  ssr: false,
  loading: PageLoading,
});
const ChooserClient = dynamic(() => import("./vidura-interview").then((m) => m.InterviewChooser), {
  ssr: false,
  loading: PageLoading,
});

/**
 * `/interview?mode=hr|panel` picks the stage; without a mode the learner chooses. The chooser
 * links to the same route, so the mode is read reactively (inside the page's Suspense boundary).
 */
function InterviewByMode() {
  const mode = useSearchParams().get("mode");
  if (mode === "hr" || mode === "panel") return <ViduraClient key={mode} mode={mode} />;
  return <ChooserClient />;
}

export function InterviewClient() {
  return (
    <Suspense fallback={<PageLoading />}>
      <InterviewByMode />
    </Suspense>
  );
}
