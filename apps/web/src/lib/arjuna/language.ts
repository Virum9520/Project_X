import { RUNNABLE_LANGUAGES, type RunnableLanguage } from "@sg/contracts";

/** The language the sandbox can run tests for; anything else falls back to Python. */
export function asRunnable(language: unknown): RunnableLanguage {
  return (RUNNABLE_LANGUAGES as readonly unknown[]).includes(language)
    ? (language as RunnableLanguage)
    : "python";
}

export const RUNNABLE_LABELS: Record<RunnableLanguage, string> = {
  python: "Python",
  javascript: "JavaScript",
  typescript: "TypeScript",
};
