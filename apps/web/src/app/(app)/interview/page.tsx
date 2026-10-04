import type { Metadata } from "next";
import Link from "next/link";

import { InterviewStage } from "@/components/interview/interview-stage";
import { getGardenData } from "@/lib/garden/data";
import { requireOnboardedLearner } from "@/lib/session";

export const metadata: Metadata = { title: "Interview practice · Skill Garden" };

const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

/**
 * `/interview?mode=hr` is Vidura's behavioural interview; `?mode=panel` is the two-person panel
 * with Arjuna. Without a mode the learner picks one.
 */
export default async function InterviewPage({ searchParams }: PageProps<"/interview">) {
  await requireOnboardedLearner();
  const params = await searchParams;
  const mode = first(params.mode);
  if (mode !== "hr" && mode !== "panel") {
    return (
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 pb-16 pt-28 sm:px-6">
        <header>
          <p className="text-xs uppercase tracking-[0.3em] text-glow">Interview practice</p>
          <h1 className="mt-1 text-3xl font-semibold">Choose your interview</h1>
        </header>
        <div className="grid gap-4 sm:grid-cols-2">
          <Link
            href={{ pathname: "/interview", query: { mode: "hr" } }}
            className="glass rounded-2xl border border-white/10 p-5 outline-none hover:border-glow/40 focus-visible:ring-2 focus-visible:ring-glow"
          >
            <h2 className="text-lg font-semibold">HR interview with Vidura</h2>
            <p className="mt-2 text-sm text-foreground/70">
              Four behavioural questions about your experience. Feedback on structure, specificity,
              ownership and conciseness.
            </p>
          </Link>
          <Link
            href={{ pathname: "/interview", query: { mode: "panel" } }}
            className="glass rounded-2xl border border-white/10 p-5 outline-none hover:border-glow/40 focus-visible:ring-2 focus-visible:ring-glow"
          >
            <h2 className="text-lg font-semibold">Panel with Vidura and Arjuna</h2>
            <p className="mt-2 text-sm text-foreground/70">
              One behavioural question, then a technical problem, with both interviewers on stage.
            </p>
          </Link>
        </div>
      </main>
    );
  }
  const { dataset, isMock } = await getGardenData();
  return (
    <InterviewStage
      mode={mode}
      dataset={dataset}
      isMock={isMock}
      viduraVrmUrl={process.env.NEXT_PUBLIC_VIDURA_VRM_URL}
      arjunaVrmUrl={process.env.NEXT_PUBLIC_ARJUNA_VRM_URL}
    />
  );
}
