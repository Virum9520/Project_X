import { notFound } from "next/navigation";

import { ArjunaDemo } from "./arjuna-demo";

export const metadata = { title: "Arjuna workbench demo" };

export default function ArjunaDevPage() {
  // Dev-only harness with mock data; hidden in production builds.
  if (process.env.NODE_ENV === "production") notFound();
  return <ArjunaDemo />;
}
