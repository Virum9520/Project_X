import { notFound } from "next/navigation";

import { getSampleGardenDataset } from "@/lib/garden/data";

import { SessionDemo } from "./session-demo";

export const metadata = { title: "Voice stage demo" };

export default function SessionDevPage() {
  // Dev-only harness; hidden in production builds.
  if (process.env.NODE_ENV === "production") notFound();
  return <SessionDemo dataset={getSampleGardenDataset()} />;
}
