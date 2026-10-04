import { notFound } from "next/navigation";

import { CoachesView } from "@/components/app-pages/coaches-view";

/** Auth-free preview of the coaches page. Development only. */
export default function CoachesPreview() {
  if (process.env.NODE_ENV === "production") notFound();
  return <CoachesView />;
}
