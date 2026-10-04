import Link from "next/link";

import { CharacterAvatar } from "@/components/character/character-avatar";
import { COACHES } from "@/components/character/coaches";

/** The six coaches: who they are and where to start with each. */
export function CoachesView() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 pb-16 pt-28 sm:px-6">
      <header>
        <p className="text-base uppercase tracking-[0.3em] text-glow">Your mentors</p>
        <h1 className="mt-1 bg-gradient-to-r from-foreground via-glow to-bloom bg-clip-text text-4xl font-semibold text-transparent sm:text-5xl">
          Coaches
        </h1>
        <p className="mt-2 max-w-2xl text-lg text-foreground/70">
          Six voices, each with one job. Talk to them out loud: what you show alone is what grows
          your garden.
        </p>
      </header>

      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {COACHES.map((c) => (
          <li
            key={c.id}
            className="glass flex flex-col items-center gap-4 rounded-3xl p-6 text-center"
          >
            <CharacterAvatar character={c.id} size={168} />
            <div>
              <h2 className="text-2xl font-semibold">{c.name}</h2>
              <p className="text-sm uppercase tracking-[0.2em] text-glow">{c.role}</p>
            </div>
            <p className="flex-1 text-foreground/70">{c.blurb}</p>
            <Link
              href={c.href}
              className="w-full rounded-xl bg-moss px-4 py-2.5 font-medium text-night outline-none transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-glow"
            >
              {c.cta}
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
