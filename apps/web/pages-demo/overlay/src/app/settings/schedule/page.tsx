import type { Metadata } from "next";

import { BhimaClient } from "@/components/practice/client-pages";

export const metadata: Metadata = { title: "Bhima call schedule · Skill Garden" };

export default function ScheduleSettingsPage() {
  return <BhimaClient />;
}
