import { notFound } from "next/navigation";

import { GardenDashboard } from "@/components/garden/dashboard";
import { getSampleGardenDataset } from "@/lib/garden/data";
import { parseState } from "@/lib/garden/state";

/**
 * Auth-free preview of the dashboard on mock data, for local development and screenshots only.
 * It 404s in production and is public in `proxy.ts` only outside production.
 */
export default async function GardenPreviewPage({ searchParams }: PageProps<"/dev/garden">) {
  if (process.env.NODE_ENV === "production") notFound();
  const [dataset, params] = await Promise.all([getSampleGardenDataset(), searchParams]);
  return <GardenDashboard dataset={dataset} initialState={parseState(params, dataset)} isMock />;
}
