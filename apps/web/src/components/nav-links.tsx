"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS: { href: Route; label: string; match: string }[] = [
  { href: "/home", label: "Home", match: "/home" },
  { href: "/garden", label: "My garden", match: "/garden" },
  { href: "/sessions", label: "Past sessions", match: "/sessions" },
  { href: "/coaches", label: "Coaches", match: "/coaches" },
];

/** The signed-in navigation. The current page is marked for sighted and assistive users. */
export function NavLinks() {
  const pathname = usePathname();
  return (
    <ul className="flex items-center gap-1 text-sm">
      {LINKS.map(({ href, label, match }) => {
        const current = pathname === match || pathname.startsWith(`${match}/`);
        return (
          <li key={href}>
            <Link
              href={href}
              aria-current={current ? "page" : undefined}
              className={`rounded-xl px-3 py-2 transition ${
                current
                  ? "bg-white/10 text-foreground"
                  : "text-foreground/70 hover:bg-white/5 hover:text-foreground"
              }`}
            >
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The marketing section links for signed-out visitors. In development only, the `/dev/app/*`
 * previews show the signed-in navigation instead, so those pages can be reviewed without a login.
 */
export function SignedOutNav({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (process.env.NODE_ENV !== "production" && pathname.startsWith("/dev/app")) return <NavLinks />;
  return children;
}
