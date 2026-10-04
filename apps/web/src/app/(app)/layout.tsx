import { requireOnboardedLearner } from "@/lib/session";

/** Everything in this group needs a signed-in learner who has finished onboarding. */
export default async function LearnerLayout({ children }: LayoutProps<"/">) {
  await requireOnboardedLearner();
  return children;
}
