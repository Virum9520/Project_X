import type { ExperienceLevel, LearnerGoal, StartingLevel, StartingLevelArea } from "@sg/contracts";

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

export const AREA_LABELS: Record<StartingLevelArea, string> = {
  dsa: "Data structures & algorithms",
  os: "Operating systems",
  networks: "Computer networks",
  databases: "Databases",
  system_design: "System design",
  behavioral: "Behavioral interviews",
};

export const LEVEL_LABELS: Record<StartingLevel, string> = {
  0: "New to it",
  1: "Know the basics",
  2: "Comfortable",
  3: "Strong",
};
