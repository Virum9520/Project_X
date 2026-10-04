"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export interface NavItem {
  href: "/" | "/users" | "/costs" | "/calls" | "/quality" | "/assistant" | "/audit";
  label: string;
}

export function Nav({ items }: { items: NavItem[] }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Console" className="flex gap-1 overflow-x-auto md:flex-col">
      {items.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`whitespace-nowrap rounded-lg px-3 py-2 text-sm ${
              active ? "bg-white/10 text-foreground" : "text-foreground/60 hover:bg-white/5"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
