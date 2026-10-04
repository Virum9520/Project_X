import type { Metadata } from "next";

import { LabClient } from "@/components/practice/client-pages";

export const metadata: Metadata = {
  title: "Garden lab · Skill Garden",
  description: "Watch a knowledge garden grow, revision by revision.",
};

export default function GardenLabPage() {
  return <LabClient />;
}
