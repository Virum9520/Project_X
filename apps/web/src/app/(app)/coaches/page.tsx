import type { Metadata } from "next";

import { CoachesView } from "@/components/app-pages/coaches-view";
import { requireOnboardedLearner } from "@/lib/session";

export const metadata: Metadata = { title: "Coaches · Skill Garden" };

export default async function CoachesPage() {
  await requireOnboardedLearner();
  return <CoachesView />;
}
