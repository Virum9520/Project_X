import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { IncomingCallScreen } from "@/components/accountability/incoming-call";
import { isUuid } from "@/lib/accountability/helpers";
import { requireOnboardedLearner } from "@/lib/session";

export const metadata: Metadata = { title: "Incoming call from Bhima · Skill Garden" };

/** Where the push notification lands: `/call/<attempt_id>`. */
export default async function CallPage({ params }: PageProps<"/call/[attemptId]">) {
  await requireOnboardedLearner();
  const { attemptId } = await params;
  if (!isUuid(attemptId)) notFound();
  return <IncomingCallScreen attemptId={attemptId} />;
}
