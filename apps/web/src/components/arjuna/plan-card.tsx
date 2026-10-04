import type { ArjunaPlan } from "@sg/contracts";

const title = (key: string) => key.split(".").pop()?.replaceAll("_", " ") ?? key;

/**
 * What Arjuna intends to cover and why. Résumé content is shown as the learner's own claims:
 * it shapes the questions but earns nothing until it is demonstrated in the interview.
 */
export function PlanCard({ plan }: { plan: ArjunaPlan }) {
  const source = [plan.has_resume && "résumé", plan.has_job_description && "job description"]
    .filter(Boolean)
    .join(" and ");
  return (
    <section aria-labelledby="plan-title" className="glass rounded-2xl p-4 sm:p-5">
      <p className="text-[0.7rem] uppercase tracking-[0.22em] text-glow">Interview plan</p>
      <h2 id="plan-title" className="mt-1 text-lg font-semibold">
        {plan.role}
      </h2>
      <p className="mt-1 text-sm text-foreground/70">
        {plan.grounded
          ? `Built from your ${source}. Résumé items are your own claims: Arjuna asks about them, and only what you demonstrate counts.`
          : "No résumé or job description matched, so Arjuna will start with fundamentals."}{" "}
        {!plan.has_resume &&
          !plan.has_job_description &&
          "Add a résumé or job description to tailor it."}
      </p>
      <ol className="mt-3 flex flex-wrap gap-2" aria-label="Topics in order">
        {plan.probes.map((p, i) => (
          <li
            key={p}
            className="rounded-full bg-white/8 px-3 py-1 text-xs capitalize ring-1 ring-white/15"
          >
            {i + 1}. {title(p)}
          </li>
        ))}
      </ol>
      {plan.problems.length > 0 && (
        <p className="mt-3 text-xs text-foreground/60">
          Likely problems: {plan.problems.map((p) => p.title).join(", ")}
        </p>
      )}
    </section>
  );
}
