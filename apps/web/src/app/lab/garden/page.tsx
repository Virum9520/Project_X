import type { Metadata } from "next";

import { GardenLab } from "./garden-lab";

export const metadata: Metadata = {
  title: "Garden lab · Skill Garden",
  description: "Development showcase for the 3D garden scene, running on mock garden data.",
  robots: { index: false },
};

/**
 * Development showcase for the 3D garden scene (C13) on mock data. The learner-facing Garden
 * Dashboard (C14) lives at `/garden` and embeds the same `GardenScene`.
 */
export default async function GardenLabPage({ searchParams }: PageProps<"/lab/garden">) {
  const { focus } = await searchParams;
  return <GardenLab initialFocus={typeof focus === "string" ? focus : null} />;
}
