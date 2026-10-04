import type { Metadata } from "next";

import { DronaClient } from "@/components/practice/client-pages";

export const metadata: Metadata = { title: "Session with Drona · Skill Garden" };

/** Drona's voice session: concept practice or Teach-back, judged against the curriculum rubric. */
export default function SessionPage() {
  return <DronaClient />;
}
