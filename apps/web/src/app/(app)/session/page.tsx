import type { Metadata } from "next";

import { SessionStage } from "@/components/session/session-stage";
import { getGardenData } from "@/lib/garden/data";
import { requireOnboardedLearner } from "@/lib/session";

export const metadata: Metadata = { title: "Session with Drona · Skill Garden" };

const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

/** The voice stage: Drona's avatar, question cards, live captions and the garden reacting. */
export default async function SessionPage({ searchParams }: PageProps<"/session">) {
  await requireOnboardedLearner();
  const [{ dataset, isMock }, params] = await Promise.all([getGardenData(), searchParams]);
  const concept = first(params.concept);
  return (
    <SessionStage
      dataset={dataset}
      isMock={isMock}
      initialConcept={concept}
      initialMode={first(params.mode) === "teach_back" ? "teach_back" : "concept_exam"}
      vrmUrl={process.env.NEXT_PUBLIC_DRONA_VRM_URL}
    />
  );
}
