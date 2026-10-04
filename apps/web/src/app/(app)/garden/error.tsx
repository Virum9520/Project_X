"use client";

/** Shown when the garden data cannot be loaded (production never substitutes sample data). */
export default function GardenError({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col items-start gap-4 px-4 pb-16 pt-32">
      <p className="text-xs uppercase tracking-[0.3em] text-glow">Garden dashboard</p>
      <h1 className="text-2xl font-semibold">Your garden can&apos;t be reached right now</h1>
      <p className="text-foreground/70">
        Your progress is safe. The service that grows your garden didn&apos;t answer, so nothing is
        shown rather than something that isn&apos;t yours.
      </p>
      <button
        type="button"
        onClick={reset}
        className="rounded-lg bg-moss px-4 py-2 text-sm font-medium text-night outline-none focus-visible:ring-2 focus-visible:ring-glow"
      >
        Try again
      </button>
    </main>
  );
}
