import type { GardenDataset } from "@sg/contracts";
import Link from "next/link";

import { CharacterAvatar } from "@/components/character/character-avatar";
import { COACH_BY_ID, COACHES } from "@/components/character/coaches";
import { formatDateTime } from "@/components/garden/primitives";

const WEEK_MS = 7 * 24 * 3600 * 1000;

/** The signed-in home screen. Pure view: the page and the dev preview supply the data. */
export function HomeView({
  name,
  dataset,
  isMock,
}: {
  name: string;
  dataset: GardenDataset;
  isMock: boolean;
}) {
  const now = Date.parse(dataset.generatedAt);
  const sessions = [...dataset.sessions].sort((a, b) => b.startedAt.localeCompare(a.startedAt));
  const last = sessions[0];
  const weekMinutes = sessions
    .filter((s) => now - Date.parse(s.startedAt) < WEEK_MS)
    .reduce((n, s) => n + s.minutes, 0);
  const next = dataset.nextBest[0];
  const nextCoach = next ? COACH_BY_ID[next.character] : COACH_BY_ID.drona;

  const tiles = [
    { label: "Day streak", value: String(dataset.streakDays) },
    { label: "Minutes this week", value: String(weekMinutes) },
    { label: "Sessions so far", value: String(sessions.length) },
    { label: "Proofs of skill", value: String(dataset.evidence.length) },
  ];

  const places = [
    { href: "/garden", title: "My garden", text: "Watch your skills grow from evidence." },
    { href: "/sessions", title: "Past sessions", text: "Every conversation and what it proved." },
    { href: "/coaches", title: "Coaches", text: "Meet the six voices and pick one." },
  ] as const;

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 pb-16 pt-28 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-base uppercase tracking-[0.3em] text-glow">Welcome back</p>
          <h1 className="mt-1 bg-gradient-to-r from-foreground via-glow to-bloom bg-clip-text text-4xl font-semibold text-transparent sm:text-5xl">
            Hello, {name}
          </h1>
        </div>
        {isMock && (
          <span className="rounded-full bg-ember/15 px-2.5 py-1 text-xs text-ember ring-1 ring-ember/40">
            Sample data
          </span>
        )}
      </header>

      <section
        aria-label="Up next"
        className="glass flex flex-wrap items-center gap-6 rounded-3xl p-6 sm:flex-nowrap"
      >
        <CharacterAvatar character={nextCoach.id} size={150} />
        <div className="min-w-0 flex-1">
          <p className="text-sm uppercase tracking-[0.2em] text-foreground/50">
            Up next · {nextCoach.name}
          </p>
          <h2 className="mt-1 text-3xl font-semibold">
            {next ? next.title : "Start your first conversation"}
          </h2>
          <p className="mt-1 text-lg text-foreground/70">
            {next ? `${next.reason} (about ${next.minutes} min)` : nextCoach.blurb}
          </p>
        </div>
        <Link
          href={
            next && (next.character === "drona" || next.character === "arjuna")
              ? { pathname: nextCoach.href, query: { concept: next.plantKey } }
              : nextCoach.href
          }
          className="rounded-xl bg-moss px-6 py-3 text-lg font-medium text-night outline-none transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-glow"
        >
          Begin
        </Link>
      </section>

      <section aria-label="Your numbers" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="glass rounded-2xl p-5">
            <p className="text-foreground/70">{t.label}</p>
            <p className="mt-1 text-5xl font-semibold text-glow">{t.value}</p>
          </div>
        ))}
      </section>

      <nav aria-label="Sections" className="grid gap-3 md:grid-cols-3">
        {places.map((p) => (
          <Link
            key={p.href}
            href={p.href}
            className="glass group rounded-2xl p-5 outline-none transition hover:-translate-y-0.5 hover:border-glow/40 focus-visible:ring-2 focus-visible:ring-glow"
          >
            <h3 className="flex items-center justify-between text-2xl font-semibold">
              {p.title}
              <span aria-hidden className="text-glow transition group-hover:translate-x-1">
                →
              </span>
            </h3>
            <p className="mt-1 text-foreground/70">{p.text}</p>
          </Link>
        ))}
      </nav>

      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <section aria-label="Last session" className="glass rounded-2xl p-5">
          <h2 className="text-sm uppercase tracking-[0.22em] text-foreground/60">Last session</h2>
          {last ? (
            <div className="mt-3 flex items-center gap-4">
              <CharacterAvatar character={last.character} size={80} />
              <div>
                <p className="text-xl font-medium">{last.title}</p>
                <p className="text-foreground/60">
                  {COACH_BY_ID[last.character].name} · {formatDateTime(last.startedAt)} ·{" "}
                  {last.minutes} min · {last.evidenceIds.length} pieces of evidence
                </p>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-foreground/70">Nothing yet. Pick a coach to begin.</p>
          )}
        </section>
        <section aria-label="Coaches" className="glass rounded-2xl p-5">
          <h2 className="text-sm uppercase tracking-[0.22em] text-foreground/60">Your coaches</h2>
          <ul className="mt-3 flex flex-wrap gap-3">
            {COACHES.map((c) => (
              <li key={c.id}>
                <Link
                  href={c.href}
                  title={`${c.name}: ${c.cta}`}
                  className="rounded-full outline-none focus-visible:ring-2 focus-visible:ring-glow"
                >
                  <CharacterAvatar character={c.id} size={64} />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
