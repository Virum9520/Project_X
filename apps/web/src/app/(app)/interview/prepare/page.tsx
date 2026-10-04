import type { ArjunaPlan, LearnerDocument } from "@sg/contracts";
import type { Metadata } from "next";

import { InterviewDocuments } from "@/components/documents/interview-documents";
import { apiGet } from "@/lib/api";
import { requireOnboardedLearner } from "@/lib/session";

export const metadata: Metadata = { title: "Interview documents · Skill Garden" };

/**
 * Upload a résumé and a job description. They feed Arjuna's interview plan only: the text is
 * stored and read as data, never as instructions, and nothing in it grows the garden.
 */
export default async function PrepareInterviewPage() {
  await requireOnboardedLearner();
  const [docs, plan] = await Promise.all([
    apiGet<LearnerDocument[]>("/v1/documents"),
    apiGet<ArjunaPlan>("/v1/arjuna/plan"),
  ]);
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-4 pb-16 pt-28 sm:px-6">
      <header>
        <p className="text-xs uppercase tracking-[0.3em] text-glow">Interview practice</p>
        <h1 className="mt-1 text-3xl font-semibold">Tailor your interview</h1>
        <p className="mt-2 max-w-2xl text-sm text-foreground/70">
          Add your résumé and the job description you are aiming for. Arjuna plans the technical
          interview around them. Only you can see these files, and you can delete them at any time.
        </p>
      </header>
      {docs.ok ? (
        <InterviewDocuments
          initialDocuments={docs.data.filter(
            (d) => d.kind === "resume" || d.kind === "job_description",
          )}
          initialPlan={plan.ok ? plan.data : null}
        />
      ) : (
        <p role="alert" className="rounded-xl bg-red-500/10 p-4 text-sm text-red-200">
          Your documents could not be loaded: {docs.detail}
        </p>
      )}
    </main>
  );
}
