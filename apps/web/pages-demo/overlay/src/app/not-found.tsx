import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-4 px-6 pb-16 pt-32 text-center">
      <p className="text-sm uppercase tracking-[0.3em] text-glow">Page not found</p>
      <h1 className="text-3xl font-semibold">Nothing grows here yet</h1>
      <p className="max-w-md text-foreground/70">
        The page you were looking for does not exist. Your garden and your coaches are a click away.
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Link
          href="/garden"
          className="rounded-xl bg-moss px-5 py-2.5 text-sm font-medium text-night outline-none hover:brightness-110 focus-visible:ring-2 focus-visible:ring-glow"
        >
          Open your garden
        </Link>
        <Link
          href="/coaches"
          className="rounded-xl border border-white/15 px-5 py-2.5 text-sm outline-none hover:border-white/30 focus-visible:ring-2 focus-visible:ring-glow"
        >
          Meet the coaches
        </Link>
      </div>
    </main>
  );
}
