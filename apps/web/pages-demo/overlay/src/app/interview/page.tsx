import type { Metadata } from "next";

import { InterviewClient } from "@/components/practice/client-pages";

export const metadata: Metadata = { title: "Interview practice · Skill Garden" };

/** `/interview?mode=hr` is Vidura's interview, `?mode=panel` the panel; otherwise a chooser. */
export default function InterviewPage() {
  return <InterviewClient />;
}
