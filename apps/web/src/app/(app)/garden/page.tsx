import type { Metadata } from "next";

import { GardenDashboard } from "@/components/garden/dashboard";
import { getGardenData } from "@/lib/garden/data";
import { parseState } from "@/lib/garden/state";
import { requireOnboardedLearner } from "@/lib/session";

export const metadata: Metadata = { title: "Garden · Skill Garden" };

/** The learner's Garden Dashboard. Filters, zoom and time travel are carried in the query string. */
export default async function GardenPage({ searchParams }: PageProps<"/garden">) {
  await requireOnboardedLearner();
  const [{ dataset, isMock, fallbackReason }, params] = await Promise.all([
    getGardenData(),
    searchParams,
  ]);
  return (
    <GardenDashboard
      dataset={dataset}
      initialState={parseState(params, dataset)}
      isMock={isMock}
      fallbackReason={fallbackReason}
    />
  );
}
