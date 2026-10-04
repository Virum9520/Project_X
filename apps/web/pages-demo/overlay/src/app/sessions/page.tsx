import type { Metadata } from "next";

import { SessionsClient } from "@/components/practice/client-pages";

export const metadata: Metadata = { title: "Past sessions · Skill Garden" };

export default function SessionsPage() {
  return <SessionsClient />;
}
