import type { ExperienceLevel, GardenDataset, OnboardingProfile } from "@sg/contracts";

type Baseline = NonNullable<GardenDataset["baseline"]>;
type Level = 0 | 1 | 2 | 3;

/** Starting level (0 new, 1 basics, 2 comfortable, 3 strong) per grove, by stated experience. */
const BY_EXPERIENCE: Record<ExperienceLevel, Required<Baseline>> = {
  "starting-out": { dsa: 1, os: 1, networks: 1, databases: 1, system_design: 0, behavioral: 1 },
  coursework: { dsa: 2, os: 2, networks: 1, databases: 1, system_design: 0, behavioral: 1 },
  projects: { dsa: 2, os: 2, networks: 2, databases: 2, system_design: 1, behavioral: 1 },
  internship: { dsa: 3, os: 2, networks: 2, databases: 2, system_design: 2, behavioral: 2 },
  professional: { dsa: 3, os: 3, networks: 3, databases: 3, system_design: 3, behavioral: 3 },
};

/**
 * A learner's self-reported baseline, derived from their onboarding answers. It seeds seedlings
 * only: it is not evidence and never counts toward readiness.
 */
export function baselineFor(profile: OnboardingProfile): Baseline {
  const base = { ...BY_EXPERIENCE[profile.experience] };
  const interviewing = profile.goals.some((g) =>
    ["behavioral-interviews", "internship-search", "job-search"].includes(g),
  );
  if (interviewing && base.behavioral === 0) base.behavioral = 1 as Level;
  return base;
}
