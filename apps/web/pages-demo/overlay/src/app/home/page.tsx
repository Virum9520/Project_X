import type { Metadata } from "next";

import { HomeClient } from "@/components/practice/client-pages";

export const metadata: Metadata = { title: "Home · Skill Garden" };

export default function HomePage() {
  return <HomeClient />;
}
