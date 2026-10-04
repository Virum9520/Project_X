import type { ArjunaPlan } from "@sg/contracts";
import type { Metadata } from "next";

import { ArjunaStage } from "@/components/arjuna/arjuna-stage";
import { apiGet } from "@/lib/api";
import { requireOnboardedLearner } from "@/lib/session";

export const metadata: Metadata = { title: "Interview with Arjuna · Skill Garden" };

const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

/**
 * The technical interview: Arjuna's avatar, a plan from the learner's résumé and job
 * description, the Monaco editor with sandboxed tests, and think-aloud captions.
 */
export default async function TechnicalInterviewPage({
  searchParams,
}: PageProps<"/interview/technical">) {
  await requireOnboardedLearner();
  const [plan, params] = await Promise.all([apiGet<ArjunaPlan>("/v1/arjuna/plan"), searchParams]);
  return (
    <ArjunaStage
      plan={plan.ok ? plan.data : null}
      initialConcept={first(params.concept)}
      vrmUrl={process.env.NEXT_PUBLIC_ARJUNA_VRM_URL}
    />
  );
}
