import type { Metadata } from "next";

import { HomeView } from "@/components/app-pages/home-view";
import { getGardenData } from "@/lib/garden/data";
import { requireOnboardedLearner } from "@/lib/session";

export const metadata: Metadata = { title: "Home · Skill Garden" };

/** Where a learner lands after signing in: what to do next, and the places to go. */
export default async function HomePage() {
  const { user } = await requireOnboardedLearner();
  const { dataset, isMock } = await getGardenData();
  return <HomeView name={user.firstName ?? "there"} dataset={dataset} isMock={isMock} />;
}
