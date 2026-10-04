import type { Metadata } from "next";

import { RecapClient } from "@/components/practice/client-pages";

export const metadata: Metadata = { title: "Weekly recap · Skill Garden" };

/** Sanjaya's weekly recap: a narrated flythrough of what grew, with the evidence behind it. */
export default function RecapPage() {
  return <RecapClient />;
}
