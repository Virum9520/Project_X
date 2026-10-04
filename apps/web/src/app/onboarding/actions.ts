"use server";

import { clerkClient } from "@clerk/nextjs/server";
import {
  EXPERIENCE_LEVELS,
  STARTING_LEVEL_AREAS,
  type StartingLevel,
  type StartingLevels,
  LEARNER_GOALS,
  type ExperienceLevel,
  type LearnerGoal,
  type OnboardingProfile,
} from "@sg/contracts";
import { redirect } from "next/navigation";

import { requireLearner } from "@/lib/session";

export type OnboardingState = { error: string | null };

export async function completeOnboarding(
  _previous: OnboardingState,
  form: FormData,
): Promise<OnboardingState> {
  const user = await requireLearner();

  const major = String(form.get("major") ?? "").trim();
  const goals = form.getAll("goals").map(String);
  const experience = String(form.get("experience") ?? "");
  const timezone = String(form.get("timezone") ?? "");

  if (major.length < 2 || major.length > 80) return { error: "Tell us your major or field." };
  if (goals.length === 0 || !goals.every((g) => LEARNER_GOALS.includes(g as LearnerGoal))) {
    return { error: "Pick at least one goal." };
  }
  if (!EXPERIENCE_LEVELS.includes(experience as ExperienceLevel)) {
    return { error: "Pick your experience level." };
  }
  if (!isTimeZone(timezone)) return { error: "Pick a valid time zone." };

  const startingLevels = Object.fromEntries(
    STARTING_LEVEL_AREAS.map((area) => {
      const n = Number(form.get(`level_${area}`));
      return [area, (Number.isInteger(n) && n >= 0 && n <= 3 ? n : 0) as StartingLevel];
    }),
  ) as StartingLevels;

  const onboarding: OnboardingProfile = {
    major,
    goals: goals as LearnerGoal[],
    experience: experience as ExperienceLevel,
    timezone,
    startingLevels,
    completedAt: new Date().toISOString(),
  };
  // publicMetadata is writable only with the secret key, so learners can't forge it client-side.
  const clerk = await clerkClient();
  await clerk.users.updateUserMetadata(user.id, { publicMetadata: { onboarding } });
  redirect("/garden");
}

function isTimeZone(value: string) {
  if (!value) return false;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: value });
    return true;
  } catch {
    return false;
  }
}
