import { DIMENSION_TO_PART } from "@sg/contracts";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-8 px-6 py-24 text-center">
      <p className="text-sm uppercase tracking-[0.3em] text-glow">Skill Garden</p>
      <h1 className="max-w-2xl text-4xl font-semibold sm:text-6xl">
        Grow real skills. <span className="text-moss">Every leaf is earned.</span>
      </h1>
      <p className="max-w-xl text-lg text-foreground/70">
        Voice mentors teach, interview and hold you accountable. Your garden only grows from what
        you actually demonstrate.
      </p>
      <ul className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        {Object.entries(DIMENSION_TO_PART).map(([dimension, part]) => (
          <li key={dimension} className="rounded-xl border border-white/10 bg-dusk/60 px-4 py-3">
            <span className="block font-medium capitalize">{dimension}</span>
            <span className="text-foreground/60">grows {part}</span>
          </li>
        ))}
      </ul>
    </main>
  );
}
