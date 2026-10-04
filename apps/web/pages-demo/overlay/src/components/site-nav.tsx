import Link from "next/link";

import { NavLinks } from "@/components/nav-links";

export function SproutMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <path d="M16 29V15" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M16 17C16 10 11 6 4 6c0 7 5 11 12 11Z" fill="var(--moss)" />
      <path d="M16 14c0-6 4-10 12-10 0 6-4 10-12 10Z" fill="var(--glow)" opacity="0.85" />
      <circle cx="16" cy="29" r="2" fill="var(--bloom)" />
    </svg>
  );
}

/** Navigation for the GitHub Pages build: the learner sections, no sign-in. */
export function SiteNav() {
  return (
    <div className="pointer-events-none fixed inset-x-0 top-4 z-50 flex justify-center px-4">
      <nav className="glass glass-nav pointer-events-auto flex w-full max-w-6xl items-center justify-between gap-4 rounded-2xl py-2.5 pl-3 pr-2.5 shadow-[0_10px_40px_-12px_rgb(0_0_0/0.6)]">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-xl bg-night/70 text-foreground">
            <SproutMark className="size-6" />
          </span>
          <span className="hidden text-xs font-medium uppercase tracking-[0.35em] sm:inline">
            Skill Garden
          </span>
        </Link>
        <NavLinks />
        <Link
          href="/coaches"
          className="hidden whitespace-nowrap rounded-xl bg-moss px-4 py-2 text-sm font-medium text-night transition hover:brightness-110 md:inline-block"
        >
          Start practising
        </Link>
      </nav>
    </div>
  );
}
