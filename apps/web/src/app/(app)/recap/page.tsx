import type { RecapPayload } from "@sg/audio";
import type { Metadata } from "next";

import { RecapPlayer } from "@/components/recap/recap-player";
import { apiGet } from "@/lib/api";
import { getGardenData } from "@/lib/garden/data";
import { requireOnboardedLearner } from "@/lib/session";

export const metadata: Metadata = { title: "Weekly recap · Skill Garden" };

/** Sanjaya's weekly recap: a narrated flythrough of what grew, with the evidence behind it. */
export default async function RecapPage() {
  await requireOnboardedLearner();
  const [{ dataset }, latest] = await Promise.all([
    getGardenData(),
    apiGet<RecapPayload>("/v1/recap/latest"),
  ]);
  return <RecapPlayer dataset={dataset} initial={latest.ok ? latest.data : null} />;
}
