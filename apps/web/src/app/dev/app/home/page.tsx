import { notFound } from "next/navigation";

import { HomeView } from "@/components/app-pages/home-view";
import { getSampleGardenDataset } from "@/lib/garden/data";

/** Auth-free preview of the signed-in home screen with the sample learner. Development only. */
export default function HomePreview() {
  if (process.env.NODE_ENV === "production") notFound();
  return <HomeView name="Virum" dataset={getSampleGardenDataset()} isMock />;
}
