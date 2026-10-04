import type { Metadata } from "next";

import { KrishnaClient } from "@/components/practice/client-pages";

export const metadata: Metadata = { title: "Future self · Skill Garden" };

export default function FutureSelfPage() {
  return <KrishnaClient />;
}
