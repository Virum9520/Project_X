import type { Metadata } from "next";

import { GardenLab } from "@/app/lab/garden/garden-lab";

export const metadata: Metadata = {
  title: "Garden lab · Skill Garden",
  description: "Simulated growth of the knowledge garden on mock data.",
};

// Static export cannot read search params on the server; deep links are not needed in the demo.
export default function GardenLabPage() {
  return <GardenLab initialFocus={null} />;
}
