import type { GardenDataset } from "@sg/contracts";
import type { Metadata } from "next";

import { GardenDashboard } from "@/components/garden/dashboard";
import { getGardenData } from "@/lib/garden/data";
import { parseState } from "@/lib/garden/state";
import { requireOnboardedLearner } from "@/lib/session";

export const metadata: Metadata = { title: "Garden · Skill Garden" };

/** The learner's Garden Dashboard. Filters, zoom and time travel are carried in the query string. */
export default async function GardenPage({ searchParams }: PageProps<"/garden">) {
  const { profile } = await requireOnboardedLearner();
  const [{ dataset, isMock, fallbackReason }, params] = await Promise.all([
    getGardenData(),
    searchParams,
  ]);
  const withBaseline: GardenDataset = {
    ...dataset,
    baseline: profile.startingLevels ?? dataset.baseline,
  };
  return (
    <GardenDashboard
      dataset={withBaseline}
      initialState={parseState(params, withBaseline)}
      isMock={isMock}
      fallbackReason={fallbackReason}
    />
  );
}
