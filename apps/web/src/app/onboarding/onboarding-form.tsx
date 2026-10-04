"use client";

import { EXPERIENCE_LEVELS, LEARNER_GOALS } from "@sg/contracts";
import { useActionState, useSyncExternalStore } from "react";

import { completeOnboarding, type OnboardingState } from "./actions";
import { EXPERIENCE_LABELS, GOAL_LABELS } from "./options";

const FALLBACK_TIMEZONE = "America/New_York";
const noSubscription = () => () => {};

export function OnboardingForm({ timezones }: { timezones: string[] }) {
  const [state, action, pending] = useActionState<OnboardingState, FormData>(completeOnboarding, {
    error: null,
  });
  const browserTimezone = useSyncExternalStore(
    noSubscription,
    () => Intl.DateTimeFormat().resolvedOptions().timeZone,
    () => "",
  );

  return (
    <form action={action} className="flex flex-col gap-8">
      <label className="flex flex-col gap-2">
        <span className="font-medium">What are you studying?</span>
        <input
          name="major"
          required
          minLength={2}
          maxLength={80}
          placeholder="Computer Science"
          className="rounded-lg border border-white/15 bg-night px-4 py-3 outline-none focus:border-moss"
        />
      </label>

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-2 font-medium">What do you want to grow?</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {LEARNER_GOALS.map((goal) => (
            <label
              key={goal}
              className="flex items-center gap-3 rounded-lg border border-white/10 bg-dusk/60 px-4 py-3 has-[:checked]:border-moss"
            >
              <input type="checkbox" name="goals" value={goal} className="accent-moss" />
              {GOAL_LABELS[goal]}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="flex flex-col gap-2">
        <span className="font-medium">Where are you so far?</span>
        <select
          name="experience"
          required
          defaultValue=""
          className="rounded-lg border border-white/15 bg-night px-4 py-3"
        >
          <option value="" disabled>
            Choose one
          </option>
          {EXPERIENCE_LEVELS.map((level) => (
            <option key={level} value={level}>
              {EXPERIENCE_LABELS[level]}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-2">
        <span className="font-medium">Your time zone</span>
        <span className="text-sm text-foreground/60">Used to schedule check-in calls.</span>
        <select
          key={browserTimezone}
          name="timezone"
          required
          defaultValue={timezones.includes(browserTimezone) ? browserTimezone : FALLBACK_TIMEZONE}
          className="rounded-lg border border-white/15 bg-night px-4 py-3"
        >
          {timezones.map((tz) => (
            <option key={tz} value={tz}>
              {tz.replaceAll("_", " ")}
            </option>
          ))}
        </select>
      </label>

      {state.error && (
        <p role="alert" className="text-sm text-bloom">
          {state.error}
        </p>
      )}

      <button
        type="submit"
        disabled={pending}
        className="rounded-full bg-moss px-6 py-3 font-medium text-night transition hover:brightness-110 disabled:opacity-60"
      >
        {pending ? "Planting your garden…" : "Plant my garden"}
      </button>
    </form>
  );
}
