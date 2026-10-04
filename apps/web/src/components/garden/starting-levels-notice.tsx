"use client";

import type { GardenDataset } from "@sg/contracts";
import { useState } from "react";

const LEVEL_WORDS = ["New to it", "Know the basics", "Comfortable", "Strong"] as const;

/** Tells a fresh learner where their garden starts and why. Shown until there is real evidence. */
export function StartingLevelsNotice({ dataset }: { dataset: GardenDataset }) {
  const [open, setOpen] = useState(true);
  const baseline = dataset.baseline;
  if (!open || !baseline || dataset.evidence.length > 0) return null;

  return (
    <section
      aria-label="Your starting levels"
      className="rounded-2xl border border-glow/30 bg-glow/10 p-5 sm:p-6"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold sm:text-3xl">Your garden starts here 🌱</h2>
          <p className="mt-2 max-w-3xl text-lg text-foreground/80">
            We planted seedlings based on your experience level. They grow into real plants when you
            prove a skill in a voice session.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Dismiss"
          className="rounded-lg px-3 py-1 text-2xl outline-none hover:bg-white/10 focus-visible:ring-2 focus-visible:ring-glow"
        >
          ×
        </button>
      </div>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {dataset.groves.map((g) => {
          const level = baseline[g.id] ?? 0;
          return (
            <li key={g.id} className="rounded-xl bg-night/60 px-4 py-3">
              <p className="text-lg font-medium">{g.title}</p>
              <p className="mt-1 text-lg text-glow">
                {LEVEL_WORDS[level]}{" "}
                <span aria-hidden className="text-foreground/40">
                  {"●".repeat(level)}
                  {"○".repeat(3 - level)}
                </span>
              </p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
