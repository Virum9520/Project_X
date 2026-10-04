import type { Metadata } from "next";

import { PrepareClient } from "@/components/practice/client-pages";

export const metadata: Metadata = { title: "Interview documents · Skill Garden" };

export default function PrepareInterviewPage() {
  return <PrepareClient />;
}
