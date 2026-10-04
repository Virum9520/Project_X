import type { ExperienceLevel } from "@sg/contracts";
import { notFound } from "next/navigation";

import { EXPERIENCE_LABELS } from "@/app/onboarding/options";
import { GardenDashboard } from "@/components/garden/dashboard";
import { getSampleGardenDataset } from "@/lib/garden/data";
import { baselineFor } from "@/lib/garden/baseline";
import { parseState } from "@/lib/garden/state";

/**
 * Auth-free preview of the dashboard on mock data, for local development and screenshots only.
 * It 404s in production and is public in `proxy.ts` only outside production.
 */
export default async function GardenPreviewPage({ searchParams }: PageProps<"/dev/garden">) {
  if (process.env.NODE_ENV === "production") notFound();
  const [sample, params] = await Promise.all([getSampleGardenDataset(), searchParams]);
  // `?fresh=<experience>` previews a brand-new account: no evidence, only the onboarding baseline.
  const fresh = typeof params.fresh === "string" ? params.fresh : null;
  const dataset =
    fresh && fresh in EXPERIENCE_LABELS
      ? {
          ...sample,
          evidence: [],
          growthEvents: [],
          sessions: [],
          memories: [],
          misconceptions: [],
          nextBest: [],
          streakDays: 0,
          baseline: baselineFor({
            major: "CS",
            goals: [],
            experience: fresh as ExperienceLevel,
            timezone: "UTC",
            completedAt: sample.generatedAt,
          }),
        }
      : sample;
  return <GardenDashboard dataset={dataset} initialState={parseState(params, dataset)} isMock />;
}
