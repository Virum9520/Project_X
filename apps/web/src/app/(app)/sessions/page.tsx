import type { Metadata } from "next";

import { SessionsView } from "@/components/app-pages/sessions-view";
import { getGardenData } from "@/lib/garden/data";
import { requireOnboardedLearner } from "@/lib/session";

export const metadata: Metadata = { title: "Past sessions · Skill Garden" };

export default async function SessionsPage() {
  await requireOnboardedLearner();
  const { dataset, isMock } = await getGardenData();
  return <SessionsView dataset={dataset} isMock={isMock} />;
}
