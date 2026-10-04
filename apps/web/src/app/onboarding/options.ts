import type { ExperienceLevel, LearnerGoal } from "@sg/contracts";

export const GOAL_LABELS: Record<LearnerGoal, string> = {
  "cs-fundamentals": "Master CS fundamentals",
  "technical-interviews": "Ace technical interviews",
  "behavioral-interviews": "Get ready for behavioral interviews",
  "internship-search": "Land an internship",
  "job-search": "Land a full-time role",
  "stay-accountable": "Stay consistent and accountable",
};

export const EXPERIENCE_LABELS: Record<ExperienceLevel, string> = {
  "starting-out": "Just starting out",
  coursework: "Taking CS coursework",
  projects: "Built a few projects",
  internship: "Done an internship",
  professional: "Working in the industry",
};
