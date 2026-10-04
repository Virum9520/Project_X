import type { Metadata } from "next";

import { ArjunaClient } from "@/components/practice/client-pages";

export const metadata: Metadata = { title: "Technical interview · Skill Garden" };

/** Arjuna's technical interview: the code runs in the browser against the problem bank's tests. */
export default function TechnicalInterviewPage() {
  return <ArjunaClient />;
}
