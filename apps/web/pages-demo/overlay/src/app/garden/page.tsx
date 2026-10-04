import type { Metadata } from "next";

import { GardenClient } from "@/components/practice/client-pages";

export const metadata: Metadata = { title: "My garden · Skill Garden" };

export default function GardenPage() {
  return <GardenClient />;
}
