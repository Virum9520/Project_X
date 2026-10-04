import type { Metadata } from "next";

import { CoachesView } from "@/components/app-pages/coaches-view";

export const metadata: Metadata = { title: "Coaches · Skill Garden" };

export default function CoachesPage() {
  return <CoachesView />;
}
