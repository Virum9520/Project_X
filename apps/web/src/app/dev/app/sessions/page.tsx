import { notFound } from "next/navigation";

import { SessionsView } from "@/components/app-pages/sessions-view";
import { getSampleGardenDataset } from "@/lib/garden/data";

/** Auth-free preview of the past-sessions page with the sample learner. Development only. */
export default function SessionsPreview() {
  if (process.env.NODE_ENV === "production") notFound();
  return <SessionsView dataset={getSampleGardenDataset()} isMock />;
}
