import type { GardenDataset } from "@sg/contracts";
import Link from "next/link";

import { CharacterAvatar } from "@/components/character/character-avatar";
import { COACH_BY_ID } from "@/components/character/coaches";
import { formatDateTime } from "@/components/garden/primitives";

/** Every session the learner has had, newest first, with how much evidence each one produced. */
export function SessionsView({ dataset, isMock }: { dataset: GardenDataset; isMock: boolean }) {
  const sessions = [...dataset.sessions].sort((a, b) => b.startedAt.localeCompare(a.startedAt));
  const totalMinutes = sessions.reduce((n, s) => n + s.minutes, 0);

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-4 pb-16 pt-28 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-base uppercase tracking-[0.3em] text-glow">History</p>
          <h1 className="mt-1 bg-gradient-to-r from-foreground via-glow to-bloom bg-clip-text text-4xl font-semibold text-transparent sm:text-5xl">
            Past sessions
          </h1>
          <p className="mt-2 text-lg text-foreground/70">
            {sessions.length} sessions · {(totalMinutes / 60).toFixed(1)} hours of practice
          </p>
        </div>
        {isMock && (
          <span className="rounded-full bg-ember/15 px-2.5 py-1 text-xs text-ember ring-1 ring-ember/40">
            Sample data
          </span>
        )}
      </header>

      {sessions.length === 0 ? (
        <div className="glass rounded-2xl p-8 text-center">
          <p className="text-xl">No sessions yet.</p>
          <p className="mt-1 text-foreground/60">Your first conversation will show up here.</p>
          <Link
            href="/coaches"
            className="mt-5 inline-block rounded-xl bg-moss px-5 py-2.5 font-medium text-night hover:brightness-110"
          >
            Meet your coaches
          </Link>
        </div>
      ) : (
        <ol className="flex flex-col gap-3">
          {sessions.map((s) => {
            const coach = COACH_BY_ID[s.character];
            return (
              <li
                key={s.id}
                className="glass flex flex-wrap items-center gap-4 rounded-2xl p-3.5 sm:flex-nowrap"
              >
                <CharacterAvatar character={s.character} size={76} />
                <div className="min-w-0 flex-1">
                  <p className="text-xs uppercase tracking-[0.2em] text-foreground/50">
                    {coach.name} · {coach.role}
                  </p>
                  <h2 className="mt-0.5 truncate text-xl font-medium">{s.title}</h2>
                  <p className="text-sm text-foreground/60">{formatDateTime(s.startedAt)}</p>
                </div>
                <dl className="flex gap-6 text-right">
                  <div>
                    <dt className="text-xs text-foreground/50">Length</dt>
                    <dd className="text-2xl font-semibold">{s.minutes}m</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-foreground/50">Evidence</dt>
                    <dd className="text-2xl font-semibold text-glow">{s.evidenceIds.length}</dd>
                  </div>
                </dl>
                <Link
                  href="/garden"
                  className="rounded-xl border border-white/15 px-3.5 py-2 text-sm outline-none hover:border-glow/40 focus-visible:ring-2 focus-visible:ring-glow"
                >
                  See in garden
                </Link>
              </li>
            );
          })}
        </ol>
      )}
    </main>
  );
}
