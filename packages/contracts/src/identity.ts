/**
 * Identity contracts mirroring `services/api` (`sg_core.identity.Capability`, `GET /v1/me`,
 * `GET /v1/admin/me`). Hand-written until OpenAPI generation lands; keep both sides in sync.
 */

/** Capabilities checked by admin endpoints. Owners hold all of them. */
export const CAPABILITIES = [
  "console.access",
  "users.read",
  "users.write",
  "usage.read",
  "calls.read",
  "calls.trigger",
  "quality.read",
  "assistant.use",
  "audit.read",
  "grants.manage",
] as const;
export type Capability = (typeof CAPABILITIES)[number];

/** `GET /v1/me`: the signed-in user as the API sees them. */
export interface Me {
  user_id: string;
  email: string | null;
  mfa_enabled: boolean;
  console_access: boolean;
  capabilities: Capability[];
}

/** `GET /v1/admin/me`: only answered for owner-console users with a second factor verified. */
export interface AdminMe {
  user_id: string;
  email: string;
  is_owner: boolean;
  mfa_verified: boolean;
  capabilities: Capability[];
}

/** Learner onboarding answers, stored in Clerk `publicMetadata.onboarding` until `profiles` exists. */
export const EXPERIENCE_LEVELS = [
  "starting-out",
  "coursework",
  "projects",
  "internship",
  "professional",
] as const;
export type ExperienceLevel = (typeof EXPERIENCE_LEVELS)[number];

export const LEARNER_GOALS = [
  "cs-fundamentals",
  "technical-interviews",
  "behavioral-interviews",
  "internship-search",
  "job-search",
  "stay-accountable",
] as const;
export type LearnerGoal = (typeof LEARNER_GOALS)[number];

/** Self-rated starting level per topic area: 0 new, 1 know the basics, 2 comfortable, 3 strong. */
export const STARTING_LEVEL_AREAS = [
  "dsa",
  "os",
  "networks",
  "databases",
  "system_design",
  "behavioral",
] as const;
export type StartingLevelArea = (typeof STARTING_LEVEL_AREAS)[number];
export type StartingLevel = 0 | 1 | 2 | 3;
export type StartingLevels = Record<StartingLevelArea, StartingLevel>;

export interface OnboardingProfile {
  major: string;
  goals: LearnerGoal[];
  experience: ExperienceLevel;
  timezone: string;
  /** Self-reported baseline. Seeds the garden's seedlings; only evidence makes plants grow. */
  startingLevels?: StartingLevels;
  completedAt: string;
}
